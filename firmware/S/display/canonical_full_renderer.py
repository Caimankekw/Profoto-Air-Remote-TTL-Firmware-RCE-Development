#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Sony canonical rows plus page, selector, MODEL and mode LCD state.

No native ABC state is changed when DEF is displayed. This component writes
only the original LCD shadow and formatter scratch. The page_hint export uses
proved A/b/C and d/E/F numeric glyphs. The Sony profile connects it to the
shared successful page-change callback and redraws on stable full release.
No separate hint timer or interrupt-dependent display policy is introduced.
"""
import importlib.util
from pathlib import Path

_spec=importlib.util.spec_from_file_location("sony_full_asm",Path(__file__).with_name("display_adapter.py"))
_asm=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_asm)
Asm=_asm.Asm
absolute=_asm.absolute


def construct(original,base,*,state_base,redraw_rows):
    if base&1 or not 0xAF80<=base<0xF800:
        raise ValueError("explicit extension code address required")
    if redraw_rows&1 or not 0xAF80<=redraw_rows<0xF800:
        raise ValueError("explicit canonical row renderer required")
    if not 0x464<=state_base or state_base+0x180>0xF00:
        raise ValueError("explicit state allocation candidate required")
    checks={0x9CB2:"498049844988",0x814C:"c10503e16b6b6b2b",0x8816:"00016b6bf3b1dba1",
            0x7B3A:"d2c0d9ffd3c0daff",0x4361:"773b0f7a1f17",0xA278:"6c510ad86d51",
            0xAEB2:"010e0001e36f010c"}
    for address,expected in checks.items():
        if original[address-0x4000:address-0x4000+len(expected)//2].hex()!=expected:
            raise ValueError(f"Sony LCD preimage mismatch at {address:04X}")
    a=Asm(base)
    def state(offset):
        a.movff(state_base+offset,0xFE8)
    a.label("redraw")
    a.call(redraw_rows)
    icons_call_offset=len(a.code)
    a.w(0,0) # Resolved to local CALL after labels are complete.
    a.goto(0xAEB2) # Mark dirty even when core runs after native51DE snapshot.
    a.label("redraw_icons")
    a.w(0x0100,0x0EC0,0x1649,0x0E2F,0x1650,0x0E7B,0x1651,0x0EFB,0x1652)
    # Mode icons preserve the native global TTL/MAN identity on either page.
    state(1);a.w(0x0900);a.goto("mode_man","NZ")
    a.w(0x8E51);a.goto("mode_done")
    a.label("mode_man");a.w(0x8451,0x8452)
    a.label("mode_done")
    # Original three row-label bits on ABC; cleared on DEF as in P8.
    state(3);a.w(0x0900);a.goto("labels_done","NZ")
    a.w(0x0E15,0x1249)
    a.label("labels_done")
    # ALL marks each visible row, as in P8; native ABC semantics stay intact.
    state(4);a.w(0x0A07);a.goto("selected_all","Z")
    for row,bit in ((1,1),(2,3),(3,5)):
        state(4);a.w(0x0A00|row);a.goto(f"selected_{row}_done","NZ")
        a.w(0x8000|(bit<<9)|0x49)
        a.label(f"selected_{row}_done")
    a.goto("selection_done")
    a.label("selected_all");a.w(0x0E2A,0x1249)
    a.label("selection_done")
    state(3);a.w(0x0900);a.goto("models_def","NZ")
    for page in (0,1):
        if page:a.label("models_def")
        for row,lcd_bit in enumerate((4,6,7)):
            mask=1<<(3*page+row)
            end=f"model_{page}_{row}_done"
            state(5);a.w(0x0B00|mask);a.goto(end,"Z")
            state(6);a.w(0x0B00|mask);a.goto(end,"Z")
            a.w(0x8000|(lcd_bit<<9)|0x50)
            a.label(end)
        a.w(0x0012)
    # Call after redraw on a confirmed page-change event; no busy wait or
    # private wall-clock guess. Next normal redraw restores numeric values.
    a.label("page_hint")
    a.w(0x0100,0x0E3F,0x1649,0x0EF0,0x1650)
    for rowno,row in enumerate((0x4A,0x4C,0x4E)):
        state(3);a.w(0x0900);a.goto(f"hint_{rowno}_def","NZ")
        a.w(0x0E00| (10+rowno));a.goto(f"hint_{rowno}_glyph")
        a.label(f"hint_{rowno}_def");a.w(0x0E00|(13+rowno))
        a.label(f"hint_{rowno}_glyph");a.w(0x6F6D,0x0E00|row,0x6F6C)
        a.call(0xA278)
        a.w(0x0E00|(row+1),0x6F6C,0x0E1A,0x6F6D)
        a.call(0xA278)
        a.w(0x9000|(7<<9)|row) # No numeric decimal in letter hint.
    a.goto(0xAEB2)
    code=bytearray(a.finish())
    code[icons_call_offset:icons_call_offset+4]=absolute(0xEC00,a.labels['redraw_icons'])
    code=bytes(code)
    if base+len(code)>0xF800:raise ValueError("renderer exceeds code limit")
    return {"sections":[{"address":base,"data":code,"role":"sony_canonical_full_renderer"}],
            "hooks":[],"exports":a.labels,"imports":{"redraw_rows":redraw_rows},"state_base":state_base,
            "native_preimages":checks,"native_fields_preserved":[0x193,0xC1,0xDB,0xF3],
            "lcd_owned_bits":{"49":"0/2/4 page labels;1/3/5 selected rows", "50":"4/6/7 visible HEAD&MODEL", "51":"2 MAN,7 TTL", "52":"2 native MAN companion"},
            "page_policy":"ABC fixed native row labels on, DEF off. Sony page_hint_on_chord invokes A/b/C or d/E/F after successful page change; release_redraw restores numbers after stable full release. A native redraw can end the hint earlier. No claimed fixed DEF glyph.",
            "dirty_contract":"redraw/page_hint tail-call nativeAEB2 to set E3=1; redraw_icons does not mark dirty",
            "complete_firmware":False}
