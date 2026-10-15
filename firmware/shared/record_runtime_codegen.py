#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Emit the pure V5 AIR2 record codec for the shared PIC18 runtime.

This module never calls native code, touches flash, or chooses a storage area.
It uses only canonical state, the 32-byte record buffer, and scratch 80..82.
Native persistence is a separately proved backend. Sequence advancement and
native-state conflict resolution belong to the caller, not this codec.
"""


RECORD_START = 0x40
RECORD_SIZE = 32
SCRATCH = (0x80, 0x81, 0x82)
EXPORTS = ("record_capture", "record_validate", "record_restore")


def emit_record(c):
    """Append capture/validate/restore routines using the shared Codegen API.

    The code generator must implement ADDWFC as file-plus-W-plus-carry, with
    W destination. ``get`` may update N/Z but must preserve C; ``put`` and
    ``literal`` also preserve C. The CRC helper depends on that ABI.

    All three exports return W=1 on success, W=0 on invalid record/state.
    Capture copies the supplied sequence without incrementing it. Restore
    revalidates before its first canonical write, leaves FEC/selector/relative
    display values/dirty tracking untouched, and performs no native apply.
    """
    profile = c.profile
    tag = profile["model_tag"] if isinstance(profile, dict) else profile.model_tag
    if not isinstance(tag, str) or len(tag) != 1 or tag not in "FNOS":
        raise ValueError("V5 AIR2 record requires model_tag F/N/O/S")

    def require_equal(offset, value):
        c.get(offset)
        c.xor_literal(value)
        c.go("record_invalid", "BNZ")

    def upper_exclusive(offset, limit):
        c.literal(limit)
        c.alu("SUBWF", offset)
        c.go("record_invalid", "BC")

    c.label("record_capture")
    for offset, value in ((0x40, 0x41), (0x41, 0x32), (0x42, 5)):
        c.set(offset, value)
    c.clear(0x43)
    c.get(0x01)
    c.go("record_capture_mode_done", "BZ")
    # Reject invalid canonical mode rather than encoding it as MAN.
    c.xor_literal(1)
    c.go("record_invalid", "BNZ")
    c.copy(0x02, 0x43)
    c.label("record_capture_mode_done")
    for source, destination in ((0x2E, 0x44), (0x2F, 0x45),
                                (0x05, 0x4C), (0x06, 0x4D),
                                (0x03, 0x4E), (0x02, 0x4F)):
        c.copy(source, destination)
    for index in range(6):
        c.copy(0x08 + index, 0x46 + index)
    c.set(0x50, ord(tag))
    for offset in range(0x51, 0x5C):
        c.clear(offset)
    c.set(0x5E, 0x5A)
    c.set(0x5F, 0xA5)
    # Validate canonical ranges before computing the CRC once. The fields
    # helper deliberately ignores the old CRC bytes, which capture replaces.
    c.call("record_validate_fields")
    c.xor_literal(0)
    c.go("record_invalid", "BZ")
    c.call("record_crc")
    c.copy(0x80, 0x5C)
    c.copy(0x81, 0x5D)
    c.ret(1)

    c.label("record_validate")
    c.call("record_validate_fields")
    c.xor_literal(0)
    c.go("record_invalid", "BZ")
    c.call("record_crc")
    c.get(0x80)
    c.alu("XORWF", 0x5C)
    c.go("record_invalid", "BNZ")
    c.get(0x81)
    c.alu("XORWF", 0x5D)
    c.go("record_invalid", "BNZ")
    c.ret(1)

    c.label("record_validate_fields")
    for offset, value in ((0x40, 0x41), (0x41, 0x32), (0x42, 5),
                          (0x50, ord(tag)), (0x5E, 0x5A), (0x5F, 0xA5)):
        require_equal(offset, value)
    for offset in range(0x51, 0x5C):
        c.get(offset)
        c.go("record_invalid", "BNZ")
    upper_exclusive(0x43, 3)
    c.get(0x4F)
    c.xor_literal(1)
    c.go("record_manual_valid", "BZ")
    require_equal(0x4F, 2)
    c.label("record_manual_valid")
    c.get(0x43)
    c.go("record_effective_valid", "BZ")
    c.alu("XORWF", 0x4F)
    c.go("record_invalid", "BNZ")
    c.label("record_effective_valid")
    for offset in range(0x46, 0x4C):
        c.get(offset)
        c.go("record_invalid", "BZ")
        upper_exclusive(offset, 101)
    for offset in (0x4C, 0x4D):
        c.get(offset)
        c.and_literal(0xC0)
        c.go("record_invalid", "BNZ")
    c.get(0x4E)
    c.and_literal(0xFE)
    c.go("record_invalid", "BNZ")
    c.ret(1)

    c.label("record_invalid")
    c.ret(0)

    c.label("record_restore")
    c.call("record_validate")
    c.xor_literal(0)
    c.go("record_invalid", "BZ")
    c.clear(0x01)
    c.get(0x43)
    c.go("record_restore_mode_done", "BZ")
    c.set(0x01, 1)
    c.label("record_restore_mode_done")
    for source, destination in ((0x4F, 0x02), (0x4E, 0x03),
                                (0x4C, 0x05), (0x4D, 0x06),
                                (0x44, 0x2E), (0x45, 0x2F)):
        c.copy(source, destination)
    for index in range(6):
        c.copy(0x46 + index, 0x08 + index)
    c.ret(1)

    c.label("record_crc")
    c.set(0x80, 0xFF)
    c.set(0x81, 0xFF)
    # A fixed 28-byte, eight-bit-per-byte calculation has a bounded run time.
    # No indirect pointers, unbounded data-dependent scans or native calls.
    for offset in range(0x40, 0x5C):
        c.get(offset)
        c.call("record_crc_byte")
    c.ret()

    c.label("record_crc_byte")
    c.alu("XORWF", 0x81)
    c.put(0x81)
    c.set(0x82, 8)
    c.label("record_crc_bit")
    c.get(0x80)
    c.alu("ADDWF", 0x80)
    c.put(0x80)
    c.get(0x81)
    c.alu("ADDWFC", 0x81)
    c.put(0x81)
    c.go("record_crc_polynomial", "BC")
    c.go("record_crc_next_bit")
    c.label("record_crc_polynomial")
    c.get(0x80)
    c.xor_literal(0x21)
    c.put(0x80)
    c.get(0x81)
    c.xor_literal(0x10)
    c.put(0x81)
    c.label("record_crc_next_bit")
    c.literal(0xFF)
    c.alu("ADDWF", 0x82)
    c.put(0x82)
    c.get(0x82)
    c.go("record_crc_bit", "BNZ")
    c.ret()

    return {
        "exports": list(EXPORTS),
        "record_range": [0x40, 0x60],
        "scratch_offsets": list(SCRATCH),
        "format_version": 5,
        "model_tag": tag,
        "native_imports": [],
        "sequence_policy": "capture copies canonical sequence; caller advances it",
    }
