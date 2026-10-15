#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Sony A6 AIR2 numeric adapter, offline construction only.

Canonical addresses must be allocated and supplied by the integration owner.
No fixed Canon extension RAM addresses, radio changes, NVM or HSS code here.
"""


def words(*items):
    return b"".join(x.to_bytes(2, "little") for x in items)


def absolute(op, target):
    if target & 1 or not 0 <= target <= 0x1FFFFE:
        raise ValueError("invalid absolute target")
    return words(op | ((target // 2) & 0xFF), 0xF000 | (target // 512))


class Asm:
    def __init__(self, base):
        self.base, self.code, self.labels, self.fixups = base, bytearray(), {}, []

    def w(self, *items):
        self.code.extend(words(*items))

    def label(self, name):
        if name in self.labels:
            raise ValueError("duplicate label")
        self.labels[name] = self.base + len(self.code)

    def movff(self, src, dest):
        self.w(0xC000 | src, 0xF000 | dest)

    def call(self, address):
        self.code.extend(absolute(0xEC00, address))

    def goto(self, target, condition=None):
        if condition is not None:
            self.w({"Z": 0xE102, "NZ": 0xE002, "NC": 0xE202}[condition])
        if isinstance(target, str):
            self.fixups.append((len(self.code), target))
            self.w(0, 0)
        else:
            self.code.extend(absolute(0xEF00, target))

    def finish(self):
        for offset, name in self.fixups:
            self.code[offset:offset + 4] = absolute(0xEF00, self.labels[name])
        return bytes(self.code)


def construct(original, base, *, targets, page, head_mask, absolute_predicate):
    """Return a component, never a flashable image.

    targets: six explicitly allocated byte addresses for A..F, values 1..100.
    page: explicit byte address, 0=ABC, 1=DEF (other values fall back).
    head_mask: explicit byte address, bits0..5 for canonical groups A..F.
    absolute_predicate: core function address, W=1 permits absolute rendering.
      Core is responsible for TTL/DEF/manual-mode policy. Other W falls back.
    """
    if len(targets) != 6 or len(set(targets)) != 6:
        raise ValueError("six distinct target addresses required")
    state = tuple(targets) + (head_mask, page)
    if len(set(state)) != 8 or any(type(x) is not int or not 0x464 <= x < 0xF00 for x in state):
        raise ValueError("supply disjoint extension SRAM outside known original 0..463 and SFRs")
    if base & 1 or base < 0xAF80:
        raise ValueError("component must start aligned after original A6 body")
    if absolute_predicate & 1 or not 0x4002 <= absolute_predicate < 0xF800:
        raise ValueError("explicit core predicate code address required")
    old = original[0x6DDE - 0x4000:0x6DE2 - 0x4000]
    if old != bytes.fromhex("48ec4bf0"):
        raise ValueError("A6 numeric-refresh preimage differs")
    a = Asm(base)
    a.label("numeric_refresh")
    a.w(0x0100)  # Native functions use BSR=0.
    a.call(absolute_predicate)
    a.w(0x0100)
    a.w(0x0A01)
    a.goto("fallback", "NZ")
    a.movff(page, 0xFE8)
    a.w(0x0900)
    a.goto("page_abc", "Z")
    a.w(0x0A01)
    a.goto("page_def", "Z")
    a.goto("fallback")
    for name, values, shift in (("page_abc", targets[:3], 0), ("page_def", targets[3:], 3)):
        a.label(name)
        # Validate the complete visible page before touching any digit.
        for target in values:
            a.movff(target, 0xFE8)
            a.w(0x0900)
            a.goto("fallback", "Z")
            a.w(0x0864)  # 100 - target, C means target <=100
            a.goto("fallback", "NC")
        for group, (row, target) in enumerate(zip((0x4A, 0x4C, 0x4E), values), shift):
            a.w(0x0E49, 0x6F6F, 0x0E00 | row, 0x6F70)
            a.movff(head_mask, 0xFE8)
            a.w(0x0B00 | (1 << group))
            a.goto(name + "_off_" + str(group), "Z")
            a.movff(target, 0x071)
            a.call(0x7584)
            a.goto(name + "_next_" + str(group))
            a.label(name + "_off_" + str(group))
            a.w(0x0E19, 0x6F71)
            a.call(0x97D8)
            a.label(name + "_next_" + str(group))
        a.goto("clear_signs")
    a.label("clear_signs")
    a.w(0x0E3F, 0x1649, 0x0EF0, 0x1650, 0x0012)
    a.label("fallback")
    a.call(0x9690)
    a.goto(0x6DE2)  # Resume exactly after displaced CALL, flags unchanged.
    code = a.finish()
    if base + len(code) > 0xF800:
        raise ValueError("component overlaps reserved upper pages")
    return {
        "code": code,
        "base": base,
        "end": base + len(code),
        "symbols": a.labels,
        "patches": [{"address": 0x6DDE, "old": old, "new": absolute(0xEF00, base)}],
        "state": {"targets": list(targets), "head_mask": head_mask, "page": page},
        "imports": {"absolute_predicate": absolute_predicate},
        "scope": "UI numeric component only; no complete firmware or device validation",
        "volatile": "W, STATUS, BSR, FSR2, TBLPTR, TABLAT and original formatter scratch 6B..75",
        "native_power_hook": {
            "address": 0x87CC,
            "old": original[0x87CC - 0x4000:0x87D2 - 0x4000].hex(),
            "bytes": 6,
            "status": "ABI evidence only; not patched by this component",
        },
    }
