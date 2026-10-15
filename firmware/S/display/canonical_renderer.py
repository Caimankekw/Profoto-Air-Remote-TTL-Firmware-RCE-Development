#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Four-kind Sony LCD row backend for shared NATIVE_BACKEND_ABI v1.

Only constructs code sections: no original image mutation or flashable output.
The integration owner supplies proven state allocation and preserves native
outer-hook context. Parent backend owns page/mode/selection/model icons.
"""
import importlib.util
from pathlib import Path

_spec=importlib.util.spec_from_file_location("sony_rows_asm",Path(__file__).with_name("display_adapter.py"))
_asm=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_asm)
Asm=_asm.Asm


def construct(original, base, *, state_base, display_row):
    if base & 1 or not 0xAF80 <= base < 0xF800:
        raise ValueError("explicit aligned extension code address required")
    if display_row & 1 or not 0x4002 <= display_row < 0xF800:
        raise ValueError("explicit core display_row address required")
    if not 0x464 <= state_base or state_base + 0x180 > 0xF00:
        raise ValueError("explicit non-overlapping state candidate required")
    # The candidate identity is checked by the model profile. Native helper
    # first instructions also prevent accepting an address-shifted model here.
    expected = {0x7584: "020e736f71af03d0", 0x97D8: "6fc06bf070c06cf0"}
    # Exact helper bytes are taken directly from the established Sony ABI.
    actual = {p: original[p-0x4000:p-0x4000+len(v)//2].hex() for p,v in expected.items()}
    if actual != expected:
        raise ValueError(f"Sony formatter preimages differ: {actual}")
    a = Asm(base)
    a.label("redraw_rows")
    for rowno, row, sign_addr, sign_mask in ((1,0x4A,0x49,0x3F), (2,0x4C,0x50,0xFC), (3,0x4E,0x50,0xF3)):
        prefix = f"row{rowno}_"
        a.w(0x0E00 | rowno)
        a.call(display_row)
        a.w(0x0100, 0x0900)
        a.goto(prefix+"blank", "Z")
        a.w(0x0A01)
        a.goto(prefix+"signed", "Z")
        a.w(0x0A03)
        a.goto(prefix+"absolute", "Z")
        a.w(0x0A01)
        a.goto(prefix+"off", "Z")
        a.goto(prefix+"blank")
        for name, glyph in (("blank",0x1A),("off",0x19)):
            a.label(prefix+name)
            a.w(0x0E49,0x6F6F,0x0E00|row,0x6F70,0x0E00|glyph,0x6F71)
            a.call(0x97D8)
            a.goto(prefix+"next")
        a.label(prefix+"signed")
        a.w(0x0E49,0x6F6F,0x0E00|row,0x6F70)
        a.movff(state_base+0x61,0x71)
        a.call(0x7584)
        a.goto(prefix+"next")
        a.label(prefix+"absolute")
        # Core guarantees 1..100. Refuse malformed absolute values as blank.
        a.movff(state_base+0x61,0xFE8)
        a.w(0x0900)
        a.goto(prefix+"blank","Z")
        a.w(0x0864)
        a.goto(prefix+"blank","NC")
        a.w(0x0E49,0x6F6F,0x0E00|row,0x6F70)
        a.movff(state_base+0x61,0x71)
        a.call(0x7584)
        # Clear only this row's sign bits: adjacent rows may be signed.
        a.w(0x0E00|sign_mask,0x1600|sign_addr)
        a.label(prefix+"next")
    a.w(0x0012)
    code = a.finish()
    if base + len(code) > 0xF800:
        raise ValueError("renderer exceeds extension code limit")
    return {"sections":[{"address":base,"data":code,"role":"sony_canonical_rows"}],
            "hooks":[],"exports":a.labels,"imports":{"display_row":display_row},
            "state_base":state_base,"native_preimages":expected,
            "scope":"All four numeric row kinds. Parent redraw adds canonical page/selection/model/mode markings.",
            "complete_firmware":False}
