#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Emit the bounded secondary-key state machine for the shared PIC18 core.

This is target-independent code generation, not a hardware driver. Native
input sampling, clock proof and original hook arbitration belong to adapters.
The generated code needs actual PIC18-VM verification before any target build
can claim this behavior. It neither scans original keys nor waits for release.

Only C/MODEL/HEAD enter the pending window. A/B/+/- remain direct core entries.
State offsets are relative to the caller's proved state allocation, and no
model-specific code, peripheral or RAM address occurs in this module.
"""


STATE = {
    "phase": 0x18, "first": 0x19, "started": (0x1A, 0x1B),
    "candidate": 0x1C, "stable_since": (0x1D, 0x1E),
    "captured_mode": 0x1F, "captured_manual": 0x20,
    "captured_page": 0x21, "captured_selector": 0x22,
    "last_tick": (0x23, 0x24), "stagnant_polls": (0x25, 0x26),
    "reserved": 0x27,
}


def emit_gestures(c):
    """Append PIC18 code using the shared Codegen API; return linkage metadata.

    ``get`` updates N/Z without changing C; ``put``, ``copy`` and ``literal``
    preserve C. This is required for the paired SUBWF/SUBWFB operations below.
    Readiness helper verifies magic A8, native-valid/edit flags and idle TX.
    Context-changing helpers perform their own apply/redraw; never duplicate
    those backend calls here.
    """
    profile = c.profile

    def profile_value(name):
        return profile[name] if isinstance(profile, dict) else getattr(profile, name)

    mask = profile_value("clock_mask")
    window = profile_value("window_counts")
    stable = profile_value("stable_counts")
    if type(mask) is not int or mask not in (0x7FFF, 0xFFFF):
        raise ValueError("gesture clock_mask must be 0x7FFF or 0xFFFF")
    for name, value in (("window_counts", window), ("stable_counts", stable)):
        if type(value) is not int or not 1 <= value <= mask:
            raise ValueError("gesture %s must be within the native clock ring" % name)

    prefix = "gesture_"

    def label(name):
        c.label(prefix + name)

    def go(name, cond=None):
        c.go(prefix + name, cond)

    def equal_literal(offset, value, target):
        c.get(offset)
        c.xor_literal(value)
        go(target, "BZ")

    def elapsed_ge(start, count, target):
        # (native_now - start) & clock_mask, full uint16 subtraction before
        # applying the explicitly selected native ring. Scratch is per call.
        c.get(start)
        c.alu("SUBWF", 0x78)
        c.put(0x64)
        c.get(start + 1)
        c.alu("SUBWFB", 0x79)
        c.and_literal(mask >> 8)
        c.put(0x65)
        c.literal(count & 0xFF)
        c.alu("SUBWF", 0x64)
        c.literal(count >> 8)
        c.alu("SUBWFB", 0x65)
        go(target, "BC")

    def valid_raw(target):
        # Avoid assumptions about electrical MODEL+HEAD coexistence. Only
        # these logical values are legal; 6/7, 0x80, 0xFF and others fail shut.
        for raw in range(6):
            equal_literal(0x7A, raw, target)
        go("cancel")

    def copy_tick(destination):
        c.copy(0x78, destination)
        c.copy(0x79, destination + 1)

    c.label("secondary_press")
    c.put(0x60)  # Preserve the caller's first key before a native backend call.
    c.backend("read_inputs")
    c.call("check_ready_edit")
    c.xor_literal(0)  # Readiness is a W result, not an implicit STATUS ABI.
    go("cancel", "BZ")
    c.get(0x18)
    go("return_zero", "BNZ")  # Re-entry must not restart a pending chord.
    for first in (1, 2, 4):
        equal_literal(0x60, first, "first_valid")
    go("cancel")

    label("first_valid")
    # Refuse a key captured against stale canonical native context. service
    # performs full reconciliation before gesture_poll; this entry only reads.
    c.get(0x70)
    c.alu("XORWF", 0x01)
    go("cancel", "BNZ")
    c.get(0x71)
    c.alu("XORWF", 0x04)
    go("cancel", "BNZ")
    c.get(0x7B)
    go("cancel", "BNZ")
    valid_raw("initial_raw_valid")

    label("initial_raw_valid")
    c.get(0x7A)
    go("begin", "BZ")  # A quick, already released native single is legal.
    c.get(0x60)
    c.alu("ANDWF", 0x7A)
    go("cancel", "BZ")

    label("begin")
    c.set(0x18, 1)
    c.copy(0x60, 0x19)
    copy_tick(0x1A)
    c.copy(0x7A, 0x1C)
    copy_tick(0x1D)
    for source, destination in ((0x01, 0x1F), (0x02, 0x20),
                                (0x03, 0x21), (0x04, 0x22)):
        c.copy(source, destination)
    copy_tick(0x23)
    c.clear(0x25)
    c.clear(0x26)
    c.clear(0x27)
    c.ret(1)

    c.label("gesture_poll")
    c.get(0x18)
    go("return_zero", "BZ")
    equal_literal(0x18, 1, "pending")
    equal_literal(0x18, 2, "release")
    go("cancel")

    label("release")
    # Any secondary or other relevant key prevents a stable full release.
    c.get(0x7B)
    go("release_held", "BNZ")
    c.get(0x7A)
    go("release_held", "BNZ")
    c.get(0x1C)
    go("release_zero_stable", "BZ")
    c.clear(0x1C)
    copy_tick(0x1D)
    c.ret(0)

    label("release_zero_stable")
    elapsed_ge(0x1D, stable, "clear")
    c.ret(0)

    label("release_held")
    c.set(0x1C, 0xFF)
    c.ret(0)

    label("clear")
    for offset in range(0x18, 0x28):
        c.clear(offset)
    # Only mounts opting into release-driven hints need this display refresh.
    # It occurs once after stable full release, never on every held-key poll.
    if profile.get("release_redraw", False):
        c.backend("redraw")
    c.ret(0)

    label("pending")
    c.call("check_ready_edit")
    c.xor_literal(0)
    go("cancel", "BZ")
    for source, captured in ((0x01, 0x1F), (0x02, 0x20),
                             (0x03, 0x21), (0x04, 0x22)):
        c.get(source)
        c.alu("XORWF", captured)
        go("cancel", "BNZ")
    c.get(0x7B)
    go("cancel", "BNZ")
    valid_raw("poll_raw_valid")

    label("poll_raw_valid")
    # A stopped native clock cannot leave the input pending forever. This is
    # a poll-count escape, deliberately not a guessed time unit or busy wait.
    c.get(0x78)
    c.alu("XORWF", 0x23)
    go("clock_advanced", "BNZ")
    c.get(0x79)
    c.alu("XORWF", 0x24)
    go("clock_advanced", "BNZ")
    c.inc(0x25)
    c.get(0x25)
    go("stall_check", "BNZ")
    c.inc(0x26)
    label("stall_check")
    c.literal(0x10)
    c.alu("SUBWF", 0x26)
    go("cancel", "BC")
    go("candidate_check")

    label("clock_advanced")
    copy_tick(0x23)
    c.clear(0x25)
    c.clear(0x26)

    label("candidate_check")
    c.get(0x7A)
    c.alu("XORWF", 0x1C)
    go("candidate_stable", "BZ")
    # Once a combo forms, neither dropping a key nor swapping combos can
    # produce its constituent single operation.
    equal_literal(0x1C, 3, "cancel")
    equal_literal(0x1C, 5, "cancel")
    equal_literal(0x7A, 3, "new_combo")
    equal_literal(0x7A, 5, "new_combo")
    c.get(0x7A)
    go("new_candidate", "BZ")
    c.alu("XORWF", 0x19)
    go("new_candidate", "BZ")
    go("cancel")

    label("new_combo")
    c.get(0x7A)
    c.alu("ANDWF", 0x19)
    go("cancel", "BZ")
    # A combo must begin strictly before the first-key deadline. A combo
    # accepted then may complete its debounce after that deadline.
    elapsed_ge(0x1A, window, "single")

    label("new_candidate")
    c.copy(0x7A, 0x1C)
    copy_tick(0x1D)
    c.ret(0)

    label("candidate_stable")
    elapsed_ge(0x1D, stable, "stable_ready")
    c.ret(0)

    label("stable_ready")
    c.get(0x7A)
    go("released_single", "BZ")
    equal_literal(0x7A, 3, "manual")
    equal_literal(0x7A, 5, "page")
    elapsed_ge(0x1A, window, "single")
    c.ret(0)

    label("single")
    # Latch before invoking UI helpers, which may enqueue a native TX plan.
    c.call(prefix + "latch")
    c.copy(0x19, 0x66)
    go("dispatch_single")

    label("released_single")
    # The release already passed debounce. Do not impose a second release
    # delay that would suppress a subsequent distinct native key event.
    c.copy(0x19, 0x66)
    for offset in range(0x18, 0x28):
        c.clear(offset)

    label("dispatch_single")
    equal_literal(0x66, 1, "single_c")
    equal_literal(0x66, 2, "single_model")
    equal_literal(0x66, 4, "single_head")
    c.ret(0)

    label("single_c")
    c.literal(3)
    c.call("select_row_internal")
    c.ret(1)

    label("single_model")
    c.call("switch_model")
    c.ret(1)

    label("single_head")
    c.call("switch_head")
    c.ret(1)

    label("manual")
    c.call(prefix + "latch")
    # The helper swallows the chord in TTL; no MODEL single leaks through.
    c.call("toggle_manual")
    c.ret(1)

    label("page")
    c.call(prefix + "latch")
    c.call("toggle_page")
    c.ret(1)

    label("cancel")
    c.call(prefix + "latch")
    label("return_zero")
    c.ret(0)

    label("latch")
    c.set(0x18, 2)
    c.set(0x1C, 0xFF)
    copy_tick(0x1D)
    c.ret()

    return {
        "exports": ["secondary_press", "gesture_poll"],
        "state": dict(STATE),
        "scratch": [0x64, 0x65, 0x66],
        "clock_mask": mask,
        "window_counts": window,
        "stable_counts": stable,
        "stagnant_poll_limit": 4096,
        "nonblocking": True,
        "verification": "PIC18 machine-code replay required",
    }
