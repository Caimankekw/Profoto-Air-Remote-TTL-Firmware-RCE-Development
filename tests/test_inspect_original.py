#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Offline checks; optional local EXE integration, never execute vendor code."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import inspect_original as inspector
from helpers.container import HexImage, RepackError
from helpers.reference_codec import CodecError, ReferenceCodec, REFERENCE_DIR

ORIGINAL = None
OTHER_ORIGINAL = None
SCRATCH = None


def scratch(label):
    global SCRATCH
    if SCRATCH is None:
        (ROOT / "outputs").mkdir(exist_ok=True)
        SCRATCH = Path(tempfile.mkdtemp(prefix="inspection-tests-", dir=str(ROOT / "outputs")))
    return SCRATCH / label


def record(address, kind, data=b""):
    raw = bytes([len(data)]) + address.to_bytes(2, "big") + bytes([kind]) + data
    return b":" + (raw + bytes([(-sum(raw)) & 255])).hex().upper().encode("ascii") + b"\r\n"


class ParserTests(unittest.TestCase):
    def test_sparse_addresses_preserved(self):
        text = record(0x4000, 0, b"\x12\x34") + record(0x4010, 0, b"\x56") + record(0, 1)
        image = HexImage(text)
        self.assertEqual(image.text, text)
        self.assertEqual(image.spans(), [(0x4000, 0x4002), (0x4010, 0x4011)])
        self.assertNotIn(0x4002, image.memory)

    def test_invalid_hex_rejected(self):
        data, eof = record(0x4000, 0, b"\x12"), record(0, 1)
        cases = {
            "checksum": data[:-4] + b"00\r\n" + eof,
            "overlap": data + data + eof,
            "cross_64k": record(0xFFFF, 0, b"\x12\x34") + eof,
            "after_eof": data + eof + data,
            "missing_eof": data,
            "unsupported_record": data + record(0, 3, b"\0\0\0\0") + eof,
        }
        for name, text in cases.items():
            with self.subTest(name=name), self.assertRaises(RepackError):
                HexImage(text)


class CodecTests(unittest.TestCase):
    def test_roundtrip_and_boundaries(self):
        codec = ReferenceCodec()
        plain = bytes(range(256)) * 191 + bytes(range(254))
        self.assertEqual(len(plain), 0x10000 - 0x4002)
        self.assertEqual(codec.decode(0x4002, codec.encode(0x4002, plain)), plain)
        self.assertEqual(codec.decode(0xFFFF, codec.encode(0xFFFF, b"\xA5")), b"\xA5")
        for address, data in [(0x4001, b"\0"), (0xFFFF, b"\0\0"), (0x10000, b"\0"), (0x4002, b""), (True, b"\0")]:
            with self.subTest(address=address, length=len(data)), self.assertRaises(CodecError):
                codec.decode(address, data)

    def test_corrupt_reference_refused(self):
        for target in ("codec_manifest.json", "c11_offset_transform.bin"):
            directory = scratch("corrupt-" + target)
            directory.mkdir()
            for name in ("codec_manifest.json", "c11_offset_transform.bin"):
                data = (REFERENCE_DIR / name).read_bytes()
                if name == target:
                    if name.endswith(".json"):
                        value = json.loads(data)
                        value["start"] += 1
                        data = inspector.json_bytes(value)
                    else:
                        data = bytes([data[0] ^ 1]) + data[1:]
                (directory / name).write_bytes(data)
            with self.subTest(target=target), self.assertRaises(CodecError):
                ReferenceCodec(directory)

    def test_header_crc_known_vector(self):
        self.assertEqual(inspector.crc16(b"123456789"), 0xBB3D)


class ProfileAndOutputTests(unittest.TestCase):
    def test_branch_profile_and_tampering(self):
        profile = inspector.load_profile()
        for key, value in [("source_sha256", "0" * 64), ("hex_start", 0),
                           ("model", "Air Remote TTL-C"), ("model", [])]:
            tampered = dict(profile)
            tampered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                inspector.validate_profile(tampered)

    def test_existing_output_always_refused_and_preserved(self):
        directory = scratch("existing-output")
        directory.mkdir()
        target = directory / "original.hex"
        target.write_bytes(b"keep this content")
        for content in (b"keep this content", b"different"):
            with self.assertRaisesRegex(ValueError, "Output already exists"):
                inspector.write_outputs(directory, {"original.hex": content})
            self.assertEqual(target.read_bytes(), b"keep this content")
        self.assertEqual([path.name for path in directory.iterdir()], ["original.hex"])

    def test_model_override_argument_is_not_supported(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "inspect_original.py"),
                                 "--original", "unused.exe", "--output", "unused-output", "--model", "N"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_local_helpers_take_precedence_over_environment(self):
        foreign = scratch("foreign-pythonpath")
        (foreign / "helpers").mkdir(parents=True)
        (foreign / "helpers" / "__init__.py").write_text("raise RuntimeError('foreign helpers loaded')\n", encoding="utf-8")
        environment = dict(os.environ, PYTHONPATH=str(foreign))
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "inspect_original.py"), "--help"],
                                env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class OriginalIntegrationTests(unittest.TestCase):
    def setUp(self):
        if ORIGINAL is None:
            self.skipTest("Supply --original for local original-EXE integration")
        self.profile = inspector.load_profile()
        self.outer = ORIGINAL.read_bytes()

    def test_original_outputs_and_unknown_ranges(self):
        output = scratch("original-success")
        before_sha = inspector.sha(self.outer)
        # Running from an unrelated CWD still uses the script's own root profile.
        cwd = scratch("unrelated-working-directory")
        cwd.mkdir()
        result = subprocess.run([sys.executable, str(ROOT / "tools" / "inspect_original.py"),
                                 "--original", str(ORIGINAL), "--output", str(output)],
                                cwd=str(cwd), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plain = (output / "original.base4000.partial.bin").read_bytes()
        mask = (output / "original.known_mask.bin").read_bytes()
        self.assertEqual(len(plain), 0x1FC00 - 0x4000)
        self.assertEqual(plain[:2], b"\0\0")
        self.assertEqual(mask, b"\0\0" + b"\1" * (len(plain) - 2))
        self.assertEqual(plain[0xC000:], b"\xff" * (0x1FC00 - 0x10000))
        for filename, key in [("original.hex", "hex_sha256"), ("original.base4000.partial.bin", "partial_plaintext_sha256"),
                              ("original.known_mask.bin", "known_mask_sha256")]:
            self.assertEqual(inspector.sha((output / filename).read_bytes()), self.profile[key])
        self.assertEqual((output / "profile.json").read_bytes(), inspector.json_bytes(self.profile))
        self.assertEqual(HexImage((output / "original.hex").read_bytes()).spans(), [(0x4000, 0x1FC10), (0x1FFF0, 0x20000)])
        report = json.loads((output / "inspection.json").read_bytes())
        self.assertFalse(report["arbitrary_full_range_decode_supported"])
        self.assertNotIn(str(ORIGINAL), (output / "inspection.json").read_text())
        self.assertEqual(inspector.sha(ORIGINAL.read_bytes()), before_sha)
        with self.assertRaisesRegex(ValueError, "Output already exists"):
            inspector.inspect_original(ORIGINAL, output)

    def test_bad_hash_and_size_create_no_output(self):
        for label, content in [("bad-hash", bytes([self.outer[0] ^ 1]) + self.outer[1:]),
                               ("bad-size", self.outer[:-1])]:
            original = scratch(label + ".input")
            original.write_bytes(content)
            output = scratch(label + "-output")
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "Original EXE"):
                inspector.inspect_original(original, output)
            self.assertFalse(output.exists())
            self.assertEqual(original.read_bytes(), content)

    def test_other_model_creates_no_output(self):
        if OTHER_ORIGINAL is None:
            self.skipTest("Supply --other-original to test another model's original EXE")
        other_data = OTHER_ORIGINAL.read_bytes()
        self.assertNotEqual(inspector.sha(other_data), self.profile["source_sha256"])
        output = scratch("wrong-model-output")
        with self.assertRaisesRegex(ValueError, "Original EXE"):
            inspector.inspect_original(OTHER_ORIGINAL, output)
        self.assertFalse(output.exists())
        self.assertEqual(OTHER_ORIGINAL.read_bytes(), other_data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--other-original", type=Path)
    args = parser.parse_args()
    ORIGINAL = args.original.resolve() if args.original else None
    OTHER_ORIGINAL = args.other_original.resolve() if args.other_original else None
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if SCRATCH is not None:
        print("Scratch retained: outputs/" + SCRATCH.name)
    sys.exit(0 if result.wasSuccessful() else 1)
