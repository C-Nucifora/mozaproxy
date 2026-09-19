"""Check actual R25 report layouts and Wine's skipped-collection failure."""
import ctypes
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def describe(data):
    """Independent HID short-item decoder for report-layout comparison."""
    globals_ = {}
    usages = []
    collections = []
    parents = []
    fields = []
    offsets = {}
    pos = 0
    while pos < len(data):
        prefix = data[pos]
        size = (0, 1, 2, 4)[prefix & 3]
        kind, tag = (prefix >> 2) & 3, prefix >> 4
        raw = data[pos + 1:pos + 1 + size]
        assert len(raw) == size
        value = int.from_bytes(raw, 'little')
        pos += size + 1
        if kind == 1:
            globals_[tag] = value
        elif kind == 2:
            usages.append((tag, globals_.get(0, 0), value))
        elif kind == 0:
            if tag == 10:
                usage = next((u[1:] for u in usages if u[0] == 0), (globals_.get(0, 0), 0))
                collections.append((usage, parents[-1] if parents else None))
                parents.append(len(collections) - 1)
            elif tag == 12:
                parents.pop()
            elif tag in (8, 9, 11):
                key = (tag, globals_.get(8, 0))
                offset = offsets.get(key, 0)
                fields.append((key, offset, dict(globals_), tuple(usages), value, tuple(parents)))
                offsets[key] = offset + globals_.get(7, 0) * globals_.get(9, 0)
            usages = []
    assert not parents
    return collections, fields


@unittest.skipUnless(shutil.which('cc'), 'C compiler required')
class HidDescriptorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = Path(cls.tmp.name) / 'hid.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        str(ROOT / 'compat/jdm_hid.c'), '-o', str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.patch = cls.lib.mozaproxy_patch_descriptor
        cls.patch.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_size_t, ctypes.c_size_t]
        cls.patch.restype = ctypes.c_size_t
        cls.original = (ROOT / 'tests/fixtures/r25-ultra-descriptor.bin').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def transform(self, data, capacity=4096):
        buf = (ctypes.c_ubyte * capacity)()
        buf[:len(data)] = data
        length = self.patch(buf, len(data), capacity)
        return bytes(buf[:length])

    def test_ffb_collection_numbers_match_hid_indices(self):
        before, _ = describe(self.original)
        self.assertTrue(any(usage[0] >= 0xff00 for usage, _ in before))
        after, _ = describe(self.transform(self.original))
        wine_nodes = [i for i, (usage, _) in enumerate(after) if 0 < usage[0] < 0xff00]
        # Wine uses sequential exported collection numbers as HID link indices.
        self.assertEqual(wine_nodes, list(range(len(after))))

    def test_all_report_fields_and_offsets_are_preserved(self):
        before, fields_before = describe(self.original)
        after, fields_after = describe(self.transform(self.original))
        self.assertEqual(fields_before, fields_after)
        self.assertEqual([p for _, p in before], [p for _, p in after])
        self.assertEqual([u for u, _ in before if u[0] == 15],
                         [u for u, _ in after if u[0] == 15])

    def test_unknown_descriptor_is_unchanged(self):
        self.assertEqual(self.transform(b'\x05\x01\x09\x04\xa1\x01\xc0'),
                         b'\x05\x01\x09\x04\xa1\x01\xc0')
        changed = bytearray(self.original)
        changed[-3] ^= 1
        self.assertEqual(self.transform(changed), changed)

    def test_insufficient_capacity_leaves_original_intact(self):
        self.assertEqual(self.transform(self.original, len(self.original)), self.original)

    def test_patch_is_idempotent(self):
        once = self.transform(self.original)
        self.assertEqual(self.transform(once), once)
