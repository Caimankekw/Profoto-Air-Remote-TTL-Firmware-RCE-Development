#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Sony A6 normal-UI secondary-press bridge; no gesture policy here.

The owner must supply complete native context preservation functions. This
component leaves sampler/debounce and +/- paths unchanged. A/B select a row
immediately through the core; only C/MODEL/HEAD use deferred gesture policy.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("sony_key_asm", Path(__file__).parents[1] / "display_adapter.py")
_asm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_asm)
Asm, absolute = _asm.Asm, _asm.absolute

KEYS = {"mode": 0x115, "aux_adc0": 0x119, "A": 0x11D, "B": 0x121,
        "C": 0x125, "model": 0x129, "head": 0x12D, "plus": 0x131,
        "minus": 0x135, "aux_portb6": 0x139, "aux_porte1": 0x13D}


def sample_history_model(memory):
    """Latest original-classifier samples, not a new physical ADC conversion."""
    secondary = sum(bit for name, bit in (("C", 1), ("model", 2), ("head", 4)) if memory[KEYS[name]] & 1)
    other = int(any(memory[address] & 1 for name, address in KEYS.items() if name not in ("C", "model", "head")))
    return secondary, other


def construct_sampler(base, *, state_base):
    """Return raw-history snapshot code writing only ABI 7A/7B.

    These are the latest original hardware classifier results, before the
    three-sample active latch. No new ADC conversion or debounce is added.
    """
    if base & 1 or not 0xAF80 <= base < 0xF800:
        raise ValueError("explicit extension code address required")
    if not 0x464 <= state_base or state_base + 0x180 > 0xF00:
        raise ValueError("explicit state allocation candidate required")
    a=Asm(base)
    a.label("sample_raw_keys")
    for offset in (0x7A,0x7B):
        addr=state_base+offset
        a.w(0x0100|(addr>>8),0x6B00|(addr&255))
    for name,address in KEYS.items():
        a.movff(address,0xFE8)
        a.w(0x0B01)
        a.goto("next_"+name,"Z")
        bit={"C":0,"model":1,"head":2}.get(name,0)
        addr=state_base+(0x7A if name in ("C","model","head") else 0x7B)
        a.w(0x0100|(addr>>8),0x8100|(bit<<9)|(addr&255))
        a.label("next_"+name)
    a.w(0x0012)
    code=a.finish()
    if base+len(code)>0xF800:
        raise ValueError("sampler exceeds extension code limit")
    return {"sections":[{"address":base,"data":code,"role":"sony_raw_key_sampler"}],
            "hooks":[],"exports":a.labels,"state_base":state_base,
            "writes":[state_base+0x7A,state_base+0x7B],"complete_firmware":False}


def construct(original, base, *, state_base, secondary_press, select_row, context_enter, context_leave):
    for address in (base, secondary_press, select_row, context_enter, context_leave):
        if address & 1 or not 0x4002 <= address < 0xF800:
            raise ValueError("explicit aligned code addresses required")
    if not 0x464 <= state_base or state_base + 0x180 > 0xF00:
        raise ValueError("explicit state allocation candidate required")
    before = original[0x8116 - 0x4000:0x811A - 0x4000]
    if before != bytes.fromhex("adef2cf0"):
        raise ValueError("Sony A6 normal-key tail preimage mismatch")
    a = Asm(base)
    a.label("secondary_dispatch")
    a.movff(state_base,0xFE8)
    a.w(0x0AA8)
    a.goto("native","NZ")
    a.w(0x0100, 0x51AC, 0x0A01)
    a.goto("native", "NZ")
    for low, name in ((0x1D,"a"),(0x21,"b"),(0x25, "c"), (0x29, "model"), (0x2D, "head")):
        a.w(0x51AB, 0x0A00 | low)
        a.goto(name, "Z")
    a.label("native")
    a.goto(0x595A)
    for name, key in (("a",1),("b",2),("c", 1), ("model", 2), ("head", 4)):
        a.label(name)
        a.call(context_enter)
        a.w(0x0E00 | key)
        a.call(select_row if name in ("a","b") else secondary_press)
        a.call(context_leave)
        a.w(0x0012)
    a.label("native_single_replay")
    # Explicit exceptional fallback only: AB/AC must be native object pointer.
    # The shared core normally executes its own single-gesture action instead.
    a.w(0x0100)
    a.goto(0x595A)
    code = a.finish()
    if base + len(code) > 0xF800:
        raise ValueError("bridge exceeds reserved-page boundary")
    return {"sections": [{"address": base, "data": code, "role": "sony_secondary_key_bridge"}],
            "hooks": [{"address": 0x8116, "expected_hex": before.hex(),
                       "new_hex": absolute(0xEF00, base).hex(), "role": "normal_key_tail", "continuation": 0x595A,
                       "evidence": "80F2 has completed native activity/input gate and DD=0 classification; AB:AC=current key object"}],
            "exports": a.labels,
            "imports": {"secondary_press": secondary_press,"select_row":select_row,"context_enter": context_enter, "context_leave": context_leave},
            "state_base":state_base,"required_runtime_magic":0xA8,
            "complete_firmware": False,
            "contract": "context helpers must preserve all live native caller scratch including 2A4/2A5 and compiler temporaries; core owns gesture policy"}
