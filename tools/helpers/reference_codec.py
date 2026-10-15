# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Offline, standard-library C11 byte transform. No USB or executable launch.

The reference table contains an address-indexed XOR byte and four bit-pair
swap controls, not device identity, a firmware image, or a device backup.
It is bounded to absolute MCU byte addresses [0x4002, 0x10000).
"""
from pathlib import Path
import hashlib
import json

ENCODABLE_START, ENCODABLE_END = 0x4002, 0x10000
TABLE_SIZE = 73725
TABLE_SHA256 = "7779d34181f9d302d2d122e9a2ed40f975a4128b738a40561f97fc86ac949303"
REFERENCE_DIR = Path(__file__).resolve().parents[1] / "reference"


class CodecError(ValueError):
    pass


def swap_pairs(value, mask):
    """Swap bit n with n+4 when control bit n is set; an involution."""
    temporary = (value ^ (value >> 4)) & mask & 15
    return value ^ temporary ^ (temporary << 4)


class ReferenceCodec:
    def __init__(self, reference_dir=None):
        directory = Path(reference_dir) if reference_dir is not None else REFERENCE_DIR
        manifest = json.loads((directory / "codec_manifest.json").read_text(encoding="utf-8"))
        expected = {
            "format": "c11-offset-transform-v1",
            "file": "c11_offset_transform.bin",
            "start": ENCODABLE_START,
            "end_exclusive": ENCODABLE_END,
            "key_bytes": ENCODABLE_END - ENCODABLE_START,
            "packed_mask_bytes": (ENCODABLE_END - ENCODABLE_START) // 2,
            "packed_mask_order": "first-address-in-low-nibble",
            "size": TABLE_SIZE,
            "sha256": TABLE_SHA256,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise CodecError("Reference manifest mismatch: " + key)
        raw = (directory / "c11_offset_transform.bin").read_bytes()
        if len(raw) != TABLE_SIZE or hashlib.sha256(raw).hexdigest() != TABLE_SHA256:
            raise CodecError("Reference transform fingerprint mismatch")
        count = ENCODABLE_END - ENCODABLE_START
        self._keys = raw[:count]
        packed = raw[count:]
        self._masks = bytes((packed[i // 2] >> (4 * (i & 1))) & 15 for i in range(count))
        self.encodable_range = (ENCODABLE_START, ENCODABLE_END)

    def _range(self, address, data):
        if type(address) is not int or not isinstance(data, (bytes, bytearray)) or not data:
            raise CodecError("Nonempty bytes and an integer absolute address are required")
        if not ENCODABLE_START <= address < address + len(data) <= ENCODABLE_END:
            raise CodecError("Requested interval is outside [0x4002, 0x10000)")
        return address - ENCODABLE_START

    def encode(self, address, plaintext):
        offset = self._range(address, plaintext)
        return bytes(swap_pairs(value, self._masks[i]) ^ self._keys[i]
                     for i, value in enumerate(plaintext, offset))

    def decode(self, address, opaque):
        offset = self._range(address, opaque)
        return bytes(swap_pairs(value ^ self._keys[i], self._masks[i])
                     for i, value in enumerate(opaque, offset))

