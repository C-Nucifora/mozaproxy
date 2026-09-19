"""Compile-time mock verification. No device descriptors are opened."""
import json
import errno
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <linux/hidraw.h>
#include <linux/magic.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <time.h>
#include <unistd.h>
static int probes, calls, clocks;
static int fake_clock_gettime(clockid_t clock, struct timespec *value)
{
    clocks++;
    return clock_gettime(clock, value);
}
#define clock_gettime fake_clock_gettime
static int fake_fstat(int fd, struct stat *data)
{
    int result = fstat(fd, data);
    if (!result && getenv("TEST_WRONG_OWNER")) data->st_uid = getuid() + 1;
    return result;
}
#define fstat fake_fstat
static long fake_raw_ioctl(int fd, unsigned long request, void *arg)
{
    (void)fd;
    probes++;
    if (request == HIDIOCGRAWINFO) {
        struct hidraw_devinfo *info = arg;
        info->vendor = getenv("TEST_OTHER") ? 0x1234 : 0x346e;
        info->product = 0;
        return 0;
    }
    if (_IOC_NR(request) == _IOC_NR(HIDIOCGRAWNAME(1))) {
        strcpy(arg, getenv("TEST_OLD_BASE") ? "MOZA R9" : "Gudsen MOZA R25 Ultra Base");
        return strlen(arg) + 1;
    }
    errno = ENOTTY;
    return -1;
}
#define MOZAPROXY_TRACE_RAW_IOCTL fake_raw_ioctl
static int fake_fstatfs(int fd, struct statfs *data)
{
    int result = fstatfs(fd, data);
    if (!result && getenv("TEST_DISK")) data->f_type = EXT4_SUPER_MAGIC;
    return result;
}
#define fstatfs fake_fstatfs
#include "TRACE_SOURCE"
static ssize_t fake_write(int fd, const void *buffer, size_t count)
{
    if (fd != 99) return syscall(SYS_write, fd, buffer, count);
    calls++;
    if (getenv("TEST_FAIL")) { errno = EFAULT; return -1; }
    return count;
}
static int fake_ioctl(int fd, unsigned long request, ...)
{
    va_list args;
    va_start(args, request);
    unsigned char *buffer = va_arg(args, unsigned char *);
    va_end(args);
    (void)fd;
    calls++;
    if (_IOC_NR(request) == _IOC_NR(HIDIOCGFEATURE(1))) {
        buffer[1] = 0x42;
        return 2;
    }
    return _IOC_SIZE(request);
}
int main(int argc, char **argv)
{
    unsigned char report[] = {5, 2, 0x9a, 0xf9};
    ssize_t result = 0;
    int saved;
    int before_calls = -1, before_probes = -1, before_clocks = -1;
    unsigned int before_attempts = 0;
    int before_done = -1;
    next_write = fake_write;
    next_ioctl = fake_ioctl;
    errno = EDOM;
    if (argc > 1 && !strcmp(argv[1], "arm")) {
        const char *marker = getenv("MOZAPROXY_JDM_TRACE_ARM");
        result = write(99, report, sizeof(report));
        result = ioctl(99, HIDIOCSFEATURE(sizeof(report)), report);
        result = ioctl(99, HIDIOCGFEATURE(sizeof(report)), report);
        before_calls = calls;
        before_probes = probes;
        before_clocks = clocks;
        before_attempts = atomic_load(&attempts);
        before_done = atomic_load(&capture_done);
        if (!marker) return 2;
        /* Replace an absent/invalid marker between real wrapper invocations. */
        unlink(marker);
        int fd = open(marker, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        if (fd < 0) return 3;
        close(fd);
        unsetenv("TEST_WRONG_OWNER");
        unsetenv("TEST_DISK");
        errno = EDOM;
        report[1] = 0x22;
        result = write(99, report, sizeof(report));
        unlink(marker);  /* Capture must remain latched after marker removal. */
        errno = EDOM;
        result = ioctl(99, HIDIOCSFEATURE(sizeof(report)), report);
        result = write(99, report, sizeof(report));
    } else if (argc > 1 && !strcmp(argv[1], "feature")) {
        result = ioctl(99, HIDIOCSFEATURE(sizeof(report)), report);
        result = ioctl(99, HIDIOCGFEATURE(sizeof(report)), report);
    } else {
        int repetitions = argc > 1 ? atoi(argv[1]) : 1;
        for (int i = 0; i < repetitions; ++i)
            result = write(99, getenv("TEST_FAIL") ? (void *)1 : report, sizeof(report));
    }
    saved = errno;
    printf("{\"result\":%zd,\"errno\":%d,\"probes\":%d,\"calls\":%d,"
           "\"clocks\":%d,\"attempts\":%u,\"done\":%d,"
           "\"before_calls\":%d,\"before_probes\":%d,\"before_clocks\":%d,"
           "\"before_attempts\":%u,\"before_done\":%d}\n", result, saved, probes, calls,
           clocks, atomic_load(&attempts), atomic_load(&capture_done),
           before_calls, before_probes, before_clocks, before_attempts, before_done);
    return 0;
}
'''


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class JdmCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.tmp.name) / 'capture-test'
        source = Path(cls.tmp.name) / 'capture-test.c'
        source.write_text(HARNESS.replace('TRACE_SOURCE', str(ROOT / 'compat/jdm_trace.c')))
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-ldl', '-pthread',
                        '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_capture(self, directory, args=(), enabled=True, extra=None):
        log = Path(directory) / 'capture.jsonl'
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('MOZAPROXY_JDM_TRACE', 'TEST_')) and k != 'LD_PRELOAD'}
        if enabled:
            env['MOZAPROXY_JDM_TRACE'] = str(log)
        env.update(extra or {})
        result = subprocess.run([str(self.binary), *args], env=env,
                                capture_output=True, text=True, check=True, timeout=5)
        events = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return json.loads(result.stdout), events

    def test_disabled_has_no_probe_or_capture_side_effects(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, enabled=False)
        self.assertEqual(result['result'], 4)
        self.assertEqual(result['probes'], 0)
        self.assertEqual(events, [])

    def test_capture_preserves_call_result_and_errno(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp)
        self.assertEqual(result['result'], 4)
        self.assertEqual(result['errno'], errno.EDOM)
        self.assertEqual(result['calls'], 1)
        self.assertEqual(events[0]['operation'], 'write')
        self.assertEqual(events[0]['hex'], '05029af9')
        self.assertEqual(events[0]['requested'], 4)
        self.assertEqual(events[0]['result'], 4)
        self.assertEqual(events[0]['errno'], 0)
        self.assertGreater(events[0]['monotonic_ns'], 0)
        self.assertEqual(result['clocks'], 2)
        self.assertEqual(result['attempts'], 1)

    def test_missing_arm_marker_forwards_without_clocks_probes_or_budget_use(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, ['10'], extra={
                'MOZAPROXY_JDM_TRACE_ARM': str(Path(tmp) / 'arm')})
        self.assertEqual(result['calls'], 10)
        self.assertEqual(result['result'], 4)
        self.assertEqual(result['errno'], errno.EDOM)
        self.assertEqual((result['probes'], result['clocks'], result['attempts'], result['done']), (0, 0, 0, 0))
        self.assertEqual(events, [])

    def test_arm_marker_created_between_calls_latches_and_preserves_full_budget(self):
        for invalid in ('missing', 'fifo', 'symlink', 'wrong_owner', 'disk'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                marker = Path(tmp) / 'arm'
                extra = {'MOZAPROXY_JDM_TRACE_ARM': str(marker), 'MOZAPROXY_JDM_TRACE_LIMIT': '2'}
                if invalid == 'fifo':
                    os.mkfifo(marker)
                elif invalid == 'symlink':
                    target = Path(tmp) / 'target'
                    target.touch()
                    marker.symlink_to(target)
                elif invalid in ('wrong_owner', 'disk'):
                    marker.touch()
                    extra['TEST_WRONG_OWNER' if invalid == 'wrong_owner' else 'TEST_DISK'] = '1'
                result, events = self.run_capture(tmp, ['arm'], extra=extra)
                self.assertEqual(result['before_calls'], 3)
                self.assertEqual((result['before_probes'], result['before_clocks'],
                                  result['before_attempts'], result['before_done']), (0, 0, 0, 0))
                self.assertEqual(result['calls'], 6)
                self.assertEqual(result['errno'], errno.EDOM)
                self.assertEqual((result['attempts'], result['done']), (2, 1))
                self.assertEqual([event['operation'] for event in events], ['write', 'set_feature'])
                self.assertEqual([event['hex'] for event in events], ['05229af9', '05229af9'])
                self.assertFalse(marker.exists())

    def test_invalid_arm_paths_remain_inactive(self):
        for invalid in ('empty', 'relative', 'directory'):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                marker = {'empty': '', 'relative': 'relative-marker', 'directory': tmp}[invalid]
                result, events = self.run_capture(tmp, ['feature'], extra={'MOZAPROXY_JDM_TRACE_ARM': marker})
                self.assertEqual(result['calls'], 2)
                self.assertEqual(result['errno'], errno.EDOM)
                self.assertEqual((result['probes'], result['clocks'], result['attempts'], result['done']), (0, 0, 0, 0))
                self.assertEqual(events, [])

    def test_nonmatching_device_ids_and_other_moza_models_are_ignored(self):
        for extra in ({'TEST_OTHER': '1'}, {'TEST_OLD_BASE': '1'}):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
                result, events = self.run_capture(tmp, extra=extra)
                self.assertEqual(result['calls'], 1)
                self.assertEqual(events, [])

    def test_failed_write_does_not_dereference_invalid_buffer(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, extra={'TEST_FAIL': '1'})
        self.assertEqual(result['result'], -1)
        self.assertEqual(result['errno'], errno.EFAULT)
        self.assertEqual(events[0]['hex'], '')
        self.assertEqual(events[0]['errno'], errno.EFAULT)

    def test_event_limit_stops_capture_without_stopping_forwarding(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, ['10'], extra={'MOZAPROXY_JDM_TRACE_LIMIT': '2'})
        self.assertEqual(result['calls'], 10)
        self.assertEqual(len(events), 2)

    def test_feature_set_and_get_replies_are_identified(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, ['feature'])
        self.assertEqual(result['calls'], 2)
        self.assertEqual([e['operation'] for e in events], ['set_feature', 'get_feature'])
        self.assertEqual(events[0]['hex'], '05029af9')
        self.assertEqual(events[1]['hex'], '0542')

    def test_existing_full_log_is_not_grown(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            log = Path(tmp) / 'capture.jsonl'
            log.write_bytes(b' ' * (1024 * 1024))
            env = dict(os.environ, MOZAPROXY_JDM_TRACE=str(log))
            env.pop('LD_PRELOAD', None)
            subprocess.run([str(self.binary)], env=env, check=True, capture_output=True)
            self.assertEqual(log.stat().st_size, 1024 * 1024)

    def test_limit_is_shared_by_separately_started_processes(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            self.run_capture(tmp, ['2'], extra={'MOZAPROXY_JDM_TRACE_LIMIT': '3'})
            result, events = self.run_capture(tmp, ['2'], extra={'MOZAPROXY_JDM_TRACE_LIMIT': '3'})
        self.assertEqual(result['calls'], 2)
        self.assertEqual(len(events), 3)

    def test_symlink_log_target_is_not_written(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            target = Path(tmp) / 'other-file'
            target.write_text('keep this')
            log = Path(tmp) / 'capture.jsonl'
            log.symlink_to(target)
            env = dict(os.environ, MOZAPROXY_JDM_TRACE=str(log))
            env.pop('LD_PRELOAD', None)
            subprocess.run([str(self.binary)], env=env, check=True, capture_output=True)
            self.assertEqual(target.read_text(), 'keep this')

    def test_non_tmpfs_output_directory_is_rejected_before_file_creation(self):
        with tempfile.TemporaryDirectory(dir='/dev/shm') as tmp:
            result, events = self.run_capture(tmp, extra={'TEST_DISK': '1'})
            self.assertFalse((Path(tmp) / 'capture.jsonl').exists())
        self.assertEqual(result['calls'], 1)
        self.assertEqual(events, [])
