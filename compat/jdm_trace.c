/* Optional, bounded observation of existing R25 hidraw output calls.
 * No reports are generated, replayed, or modified by this library.
 * Put it BEFORE jdm_hid.so in LD_PRELOAD so ioctl interposition chains.
 * Enable only with MOZAPROXY_JDM_TRACE=/absolute/path/to/capture.jsonl.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/hidraw.h>
#include <linux/magic.h>
#include <limits.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <time.h>
#include <unistd.h>

#define TRACE_MAX_BYTES (1024 * 1024)
#define TRACE_MAX_PAYLOAD 128
#define TRACE_DEFAULT_EVENTS 512
#define TRACE_MAX_EVENTS 4096

static ssize_t (*next_write)(int, const void *, size_t);
static int (*next_ioctl)(int, unsigned long, ...);
static _Atomic unsigned int attempts;
static _Atomic int capture_done;
static _Atomic int capture_armed;
static __thread int tracing;

__attribute__((constructor)) static void resolve_next(void)
{
    next_write = dlsym(RTLD_NEXT, "write");
    next_ioctl = dlsym(RTLD_NEXT, "ioctl");
}

#ifndef MOZAPROXY_TRACE_RAW_IOCTL
static long raw_ioctl(int fd, unsigned long request, void *arg)
{
    return syscall(SYS_ioctl, fd, request, arg);
}
#define MOZAPROXY_TRACE_RAW_IOCTL raw_ioctl
#endif

static int trace_configuration(const char **path)
{
    const char *value;
    char *end;
    unsigned long limit = TRACE_DEFAULT_EVENTS;
    *path = getenv("MOZAPROXY_JDM_TRACE");
    if (!*path || (*path)[0] != '/') return 0;
    value = getenv("MOZAPROXY_JDM_TRACE_LIMIT");
    if (value) {
        if (!*value || *value == '-') return 0;
        limit = strtoul(value, &end, 10);
        if (*end || !limit) return 0;
        if (limit > TRACE_MAX_EVENTS) limit = TRACE_MAX_EVENTS;
    }
    return limit;
}

/* O_PATH inspects metadata without activating devices or waiting on FIFOs.
 * Invalid markers remain retryable; one valid marker arms this process once.
 */
static int arm_ready(void)
{
    if (atomic_load(&capture_armed)) return 1;
    const char *marker = getenv("MOZAPROXY_JDM_TRACE_ARM");
    if (!marker) return 1;
    if (marker[0] != '/') return 0;
    int fd = open(marker, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 0;
    struct stat status;
    struct statfs filesystem;
    int valid = !fstat(fd, &status) && S_ISREG(status.st_mode) &&
                status.st_uid == getuid() && !fstatfs(fd, &filesystem) &&
                filesystem.f_type == TMPFS_MAGIC;
    close(fd);
    if (valid) atomic_store(&capture_armed, 1);
    return valid;
}

static uint64_t monotonic_ns(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    return (uint64_t)now.tv_sec * UINT64_C(1000000000) + now.tv_nsec;
}

static int is_r25(int fd)
{
    struct hidraw_devinfo info;
    char name[128] = {0};
    char *model;
    if (MOZAPROXY_TRACE_RAW_IOCTL(fd, HIDIOCGRAWINFO, &info) < 0 ||
        info.vendor != 0x346e || info.product != 0) return 0;
    if (MOZAPROXY_TRACE_RAW_IOCTL(fd, HIDIOCGRAWNAME(sizeof(name) - 1), name) < 0) return 0;
    model = strstr(name, "MOZA R25");
    return model && (model[8] == ' ' || model[8] == '\0');
}

/* Count while locked so independently launched processes share the same cap.
 * Each append opens a distinct descriptor; forked processes cannot accidentally
 * share a flock owner. Contended locks skip records rather than blocking FFB.
 */
static int below_event_limit(int fd, const struct stat *status, unsigned int limit)
{
    static __thread dev_t cached_device;
    static __thread ino_t cached_inode;
    static __thread off_t offset;
    static __thread unsigned int lines;
    char buffer[4096];
    if (cached_device != status->st_dev || cached_inode != status->st_ino || offset > status->st_size) {
        cached_device = status->st_dev;
        cached_inode = status->st_ino;
        offset = 0;
        lines = 0;
    }
    if (lines >= limit) return 0;
    while (offset < status->st_size) {
        ssize_t count = pread(fd, buffer, sizeof(buffer), offset);
        if (count <= 0) return 0;
        for (ssize_t i = 0; i < count; ++i)
            if (buffer[i] == '\n' && ++lines >= limit) return 0;
        offset += count;
    }
    return 1;
}

static int open_trace_file(const char *path)
{
    char directory[PATH_MAX];
    const char *name = strrchr(path, '/');
    size_t length = name - path;
    struct statfs filesystem;
    if (!name[1] || length >= sizeof(directory)) return -1;
    memcpy(directory, path, length);
    directory[length] = 0;
    int parent = open(length ? directory : "/", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (parent < 0) return -1;
    int fd = -1;
    if (!fstatfs(parent, &filesystem) && filesystem.f_type == TMPFS_MAGIC)
        fd = openat(parent, name + 1, O_RDWR | O_CREAT | O_APPEND | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    close(parent);
    return fd;
}

static void record_call(int device_fd, const char *operation, unsigned long request,
                        const void *data, size_t requested, ssize_t result, int error,
                        uint64_t started, uint64_t finished, int is_get)
{
    const char *path;
    int limit = trace_configuration(&path);
    if (!limit || atomic_load(&attempts) >= (unsigned int)limit || !is_r25(device_fd)) return;
    unsigned int index = atomic_fetch_add(&attempts, 1);
    if (index + 1 >= (unsigned int)limit) atomic_store(&capture_done, 1);
    if (index >= (unsigned int)limit) return;

    size_t available = result < 0 ? 0 : requested;
    if (is_get || !strcmp(operation, "write"))
        available = result > 0 && (size_t)result < requested ? (size_t)result : available;
    if (!result && (is_get || !strcmp(operation, "write"))) available = 0;
    size_t captured = available < TRACE_MAX_PAYLOAD ? available : TRACE_MAX_PAYLOAD;
    char hex[TRACE_MAX_PAYLOAD * 2 + 1];
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < captured; ++i) {
        unsigned char byte = ((const unsigned char *)data)[i];
        hex[i * 2] = digits[byte >> 4];
        hex[i * 2 + 1] = digits[byte & 15];
    }
    hex[captured * 2] = 0;
    char line[1024];
    int length = snprintf(line, sizeof(line),
        "{\"pid\":%ld,\"tid\":%ld,\"fd\":%d,\"operation\":\"%s\","
        "\"request\":\"0x%lx\",\"monotonic_ns\":%llu,\"elapsed_ns\":%llu,"
        "\"requested\":%zu,\"result\":%zd,\"errno\":%d,\"hex\":\"%s\",\"truncated\":%s}\n",
        (long)getpid(), (long)syscall(SYS_gettid), device_fd, operation, request,
        (unsigned long long)started, (unsigned long long)(finished >= started ? finished - started : 0),
        requested, result, result < 0 ? error : 0, hex, available > captured ? "true" : "false");
    if (length <= 0 || (size_t)length >= sizeof(line)) return;

    int fd = open_trace_file(path);
    if (fd < 0) { atomic_store(&capture_done, 1); return; }
    struct stat status;
    if (fstat(fd, &status) || !S_ISREG(status.st_mode) || status.st_uid != getuid()) goto done;
    if (flock(fd, LOCK_EX | LOCK_NB)) goto done;
    if (fstat(fd, &status) || status.st_size < 0 || status.st_size > TRACE_MAX_BYTES - length) {
        atomic_store(&capture_done, 1);
        goto done;
    }
    if (!below_event_limit(fd, &status, limit)) {
        atomic_store(&capture_done, 1);
        goto done;
    }
    /* A raw syscall prevents recursively recording writes to the log itself. */
    (void)syscall(SYS_write, fd, line, (size_t)length);
done:
    close(fd);
}

ssize_t write(int fd, const void *data, size_t count)
{
    const char *path;
    int before = errno;
    int enabled = !tracing && !atomic_load(&capture_done) &&
                  trace_configuration(&path) && arm_ready();
    uint64_t started = enabled ? monotonic_ns() : 0;
    errno = before;
    ssize_t result = next_write ? next_write(fd, data, count) : syscall(SYS_write, fd, data, count);
    int saved = errno;
    if (enabled) {
        uint64_t finished = monotonic_ns();
        tracing = 1;
        record_call(fd, "write", 0, data, count, result, saved, started, finished, 0);
        tracing = 0;
    }
    errno = saved;
    return result;
}

int ioctl(int fd, unsigned long request, ...)
{
    va_list args;
    va_start(args, request);
    void *arg = va_arg(args, void *);
    va_end(args);
    unsigned long kind = request & ~((unsigned long)_IOC_SIZEMASK << _IOC_SIZESHIFT);
    int set = kind == HIDIOCSFEATURE(0), get = kind == HIDIOCGFEATURE(0);
    const char *path;
    int before = errno;
    int enabled = (set || get) && !tracing && !atomic_load(&capture_done) &&
                  trace_configuration(&path) && arm_ready();
    uint64_t started = enabled ? monotonic_ns() : 0;
    errno = before;
    int result = next_ioctl ? next_ioctl(fd, request, arg) : syscall(SYS_ioctl, fd, request, arg);
    int saved = errno;
    if (enabled) {
        uint64_t finished = monotonic_ns();
        tracing = 1;
        record_call(fd, get ? "get_feature" : "set_feature", request, arg, _IOC_SIZE(request),
                    result, saved, started, finished, get);
        tracing = 0;
    }
    errno = saved;
    return result;
}
