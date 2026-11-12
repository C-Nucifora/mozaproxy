/* LMU-only evdev workaround: expire streamed constant force between updates.
 * Build: cc -shared -fPIC -O2 -Wall -Wextra -Werror -pthread \
 *           tools/lmu_ffb_guard.c -ldl -o lmu_ffb_guard.so
 * Load only for LMU, never globally. See docs/lmu-pause.md.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <linux/input.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define GUARDED_FDS 4096
#define FORCE_LIFETIME_MS 50

static int (*next_ioctl)(int, unsigned long, ...);
static ssize_t (*next_write)(int, const void *, size_t);
static int (*next_close)(int);
static pthread_once_t once = PTHREAD_ONCE_INIT;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct {
    bool identified, target, announced;
    dev_t device;
    ino_t inode;
    bool guarded[FF_MAX_EFFECTS], playing[FF_MAX_EFFECTS];
} devices[GUARDED_FDS];

static void before_fork(void) { pthread_mutex_lock(&lock); }
static void after_fork(void) { pthread_mutex_unlock(&lock); }

static int enter(void)
{
    int cancellation;
    pthread_setcancelstate(PTHREAD_CANCEL_DISABLE, &cancellation);
    pthread_mutex_lock(&lock);
    return cancellation;
}

static void leave(int cancellation)
{
    pthread_mutex_unlock(&lock);
    pthread_setcancelstate(cancellation, NULL);
}

static void resolve(void)
{
    next_ioctl = dlsym(RTLD_NEXT, "ioctl");
    next_write = dlsym(RTLD_NEXT, "write");
    next_close = dlsym(RTLD_NEXT, "close");
    if (!next_ioctl || !next_write || !next_close) _exit(127);
    if (pthread_atfork(before_fork, after_fork, after_fork)) _exit(127);
}

__attribute__((constructor)) static void initialize(void)
{
    pthread_once(&once, resolve);
}

/* dup2 and close_range can replace a descriptor without calling close. */
static bool same_device(int fd)
{
    struct stat st;
    if (fstat(fd, &st) == 0 && S_ISCHR(st.st_mode) &&
        st.st_dev == devices[fd].device && st.st_ino == devices[fd].inode)
        return true;
    memset(&devices[fd], 0, sizeof(devices[fd]));
    return false;
}

/* Called only for effect uploads, under lock. No device is opened or grabbed. */
static bool is_target(int fd)
{
    struct input_id id;
    char name[128] = {0};
    struct stat st;
    if (fd < 0 || fd >= GUARDED_FDS) return false;
    if (devices[fd].identified) same_device(fd);
    if (!devices[fd].identified) {
        devices[fd].target =
            fstat(fd, &st) == 0 && S_ISCHR(st.st_mode) &&
            next_ioctl(fd, EVIOCGID, &id) == 0 &&
            id.vendor == 0x346e && id.product == 0x0000 &&
            next_ioctl(fd, EVIOCGNAME(sizeof(name)), name) >= 0 &&
            !strcmp(name, "Gudsen MOZA R25 Ultra Base");
        devices[fd].identified = true;
        if (devices[fd].target) {
            devices[fd].device = st.st_dev;
            devices[fd].inode = st.st_ino;
            const char msg[] = "lmu_ffb_guard: R25 streamed constant force expires after 50 ms\n";
            next_write(STDERR_FILENO, msg, sizeof(msg) - 1);
        }
    }
    return devices[fd].target;
}

int ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    unsigned long arg = va_arg(ap, unsigned long);
    va_end(ap);
    pthread_once(&once, resolve);
    if (request != EVIOCSFF && request != EVIOCRMFF)
        return next_ioctl(fd, request, arg);

    int cancellation = enter();
    if (!is_target(fd)) {
        leave(cancellation);
        return next_ioctl(fd, request, arg);
    }

    int result;
    if (request == EVIOCSFF && arg) {
        struct ff_effect *original = (void *)arg;
        struct ff_effect effect = *original;
        bool guarded = effect.type == FF_CONSTANT && !effect.replay.length &&
            !effect.replay.delay && !effect.trigger.button &&
            !effect.u.constant.envelope.attack_length &&
            !effect.u.constant.envelope.fade_length;
        bool updating = effect.id >= 0 && effect.id < FF_MAX_EFFECTS;
        if (guarded) effect.replay.length = FORCE_LIFETIME_MS;
        result = next_ioctl(fd, request, &effect);
        if (result >= 0 && effect.id >= 0 && effect.id < FF_MAX_EFFECTS) {
            original->id = effect.id;
            devices[fd].guarded[effect.id] = guarded;
            if (guarded && !devices[fd].announced) {
                const char msg[] = "lmu_ffb_guard: bounded constant effect uploaded successfully\n";
                next_write(STDERR_FILENO, msg, sizeof(msg) - 1);
                devices[fd].announced = true;
            }
            if (!updating) devices[fd].playing[effect.id] = false;
            if (guarded && devices[fd].playing[effect.id]) {
                /* Renew only an effect the game started, including after expiry. */
                struct input_event play = {.type = EV_FF, .code = (unsigned short)effect.id, .value = 1};
                ssize_t written = next_write(fd, &play, sizeof(play));
                if (written != sizeof(play)) {
                    if (written >= 0) errno = EIO;
                    result = -1;
                }
            }
        }
    } else {
        result = next_ioctl(fd, request, arg);
        if (result >= 0 && request == EVIOCRMFF && arg < FF_MAX_EFFECTS) {
            devices[fd].guarded[arg] = false;
            devices[fd].playing[arg] = false;
        }
    }
    int saved_errno = errno;
    leave(cancellation);
    errno = saved_errno;
    return result;
}

ssize_t write(int fd, const void *buf, size_t size)
{
    pthread_once(&once, resolve);
    if (fd < 0 || fd >= GUARDED_FDS || !size || size % sizeof(struct input_event))
        return next_write(fd, buf, size);

    int cancellation = enter();
    if (!devices[fd].target || !same_device(fd)) {
        leave(cancellation);
        return next_write(fd, buf, size);
    }
    struct input_event *events = malloc(size);
    if (!events) {
        leave(cancellation);
        errno = ENOMEM;
        return -1;
    }
    memcpy(events, buf, size);
    for (size_t i = 0; i < size / sizeof(*events); ++i) {
        unsigned code = events[i].code;
        if (events[i].type == EV_FF && code < FF_MAX_EFFECTS &&
            devices[fd].guarded[code] && events[i].value > 0)
            events[i].value = 1; /* Never loop an expired force indefinitely. */
    }
    ssize_t result = next_write(fd, events, size);
    int saved_errno = errno;
    for (size_t i = 0; result > 0 && i < (size_t)result / sizeof(*events); ++i) {
        unsigned code = events[i].code;
        if (events[i].type == EV_FF && code < FF_MAX_EFFECTS && events[i].value >= 0)
            devices[fd].playing[code] = events[i].value > 0;
    }
    free(events);
    leave(cancellation);
    errno = saved_errno;
    return result;
}

int close(int fd)
{
    pthread_once(&once, resolve);
    int cancellation = enter();
    int result = next_close(fd);
    int saved_errno = errno;
    if (fd >= 0 && fd < GUARDED_FDS) memset(&devices[fd], 0, sizeof(devices[fd]));
    leave(cancellation);
    errno = saved_errno;
    return result;
}
