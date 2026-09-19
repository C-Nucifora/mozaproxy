/*
 * JDM / Wine workaround for the captured MOZA R25 Ultra descriptor.
 * Wine skips vendor collections when numbering DirectInput objects, but uses
 * those numbers as unfiltered HID link indices for PID force feedback.
 * Describe the vendor container as Generic Desktop / Pointer, then restore
 * the vendor usage page immediately. Every report field and byte stays intact.
 * This is process-local; it never changes the kernel or device descriptor.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <linux/hidraw.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <unistd.h>

size_t mozaproxy_patch_descriptor(uint8_t *data, size_t size, size_t capacity)
{
    static const uint8_t old[] = {0x06,0x00,0xff,0x09,0x00,0xa1,0x01};
    static const uint8_t replacement[] = {0x05,0x01,0x09,0x01,0xa1,0x01,0x06,0x00,0xff};
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    const size_t offset = 114;
    if (size != 1315 || capacity < size + 2) return size;
    for (size_t i = 0; i < size; ++i) hash = (hash ^ data[i]) * UINT64_C(0x100000001b3);
    /* Fail closed on any untested firmware descriptor, even the same length. */
    if (hash != UINT64_C(0x4d9172d7aec22cb7) || memcmp(data + offset, old, sizeof(old))) return size;
    memmove(data + offset + sizeof(replacement), data + offset + sizeof(old),
            size - offset - sizeof(old));
    memcpy(data + offset, replacement, sizeof(replacement));
    return size + 2;
}

static int fixed_descriptor(int fd, struct hidraw_report_descriptor *desc)
{
    struct hidraw_devinfo info;
    int size;
    if (syscall(SYS_ioctl, fd, HIDIOCGRAWINFO, &info) < 0 ||
        info.vendor != 0x346e || info.product != 0x0000) return 0;
    if (syscall(SYS_ioctl, fd, HIDIOCGRDESCSIZE, &size) < 0 || size != 1315) return 0;
    memset(desc, 0, sizeof(*desc));
    desc->size = size;
    if (syscall(SYS_ioctl, fd, HIDIOCGRDESC, desc) < 0) return 0;
    size_t changed = mozaproxy_patch_descriptor(desc->value, size, sizeof(desc->value));
    if (changed == (size_t)size) return 0;
    desc->size = changed;
    return 1;
}

int ioctl(int fd, unsigned long request, ...)
{
    va_list args;
    va_start(args, request);
    void *arg = va_arg(args, void *);
    va_end(args);
    int ret = syscall(SYS_ioctl, fd, request, arg);
    int saved_errno = errno;
    if (ret >= 0 && (request == HIDIOCGRDESCSIZE || request == HIDIOCGRDESC)) {
        struct hidraw_report_descriptor desc;
        if (fixed_descriptor(fd, &desc)) {
            if (request == HIDIOCGRDESCSIZE) *(int *)arg = desc.size;
            else {
                struct hidraw_report_descriptor *out = arg;
                if (out->size >= desc.size) {
                    memcpy(out->value, desc.value, desc.size);
                    out->size = desc.size;
                    fprintf(stderr, "mozaproxy: applied R25 Wine FFB collection workaround\n");
                }
            }
        }
    }
    errno = saved_errno;
    return ret;
}
