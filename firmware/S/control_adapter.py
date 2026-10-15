#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Sony foreground power/display/native-idle hook wrappers, no HSS hooks."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_control_asm', HERE/'display/display_adapter.py')
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)


def construct(original, *, base, state_base, context_enter, context_leave,
              power_edit, redraw, idle_expired):
    if base & 1 or base < 0xAF80:
        raise ValueError('explicit Sony extension placement required')
    for entry in (context_enter, context_leave, power_edit, redraw, idle_expired):
        if type(entry) is not int or entry & 1 or not 0xAF80 <= entry < 0xF800:
            raise ValueError('resolved extension imports required')
    if state_base < 0x464 or state_base+0x180 > 0xF00:
        raise ValueError('explicit disjoint state SRAM required')
    preimages = {0x87CC: 'a36f48ec4bf0', 0x6DDE: '48ec4bf0',
                 0x8062: 'd2c0d9ffd3c0daff', 0x807A: 'ec6bed6bee6b'}
    for addr, raw in preimages.items():
        if original[addr-0x4000:addr-0x4000+len(raw)//2].hex() != raw:
            raise ValueError('Sony control hook preimage differs: %04X' % addr)
    a = assembler.Asm(base)
    s = state_base
    step = s + 0x116

    def eligibility(fallback):
        a.movff(s, 0xFE8)
        a.w(0x0AA8)
        a.goto(fallback, 'NZ')
        a.movff(0xDD, 0xFE8)
        a.w(0x0900)
        a.goto(fallback, 'NZ')

    a.label('power_hook')
    a.call(context_enter)
    a.movff(0xFE8, step)
    eligibility('power_native')
    a.movff(step, 0xFE8)
    a.call(power_edit)
    # Rejected edits in active AIR2 also stay rejected; no old relative send.
    a.call(context_leave)
    a.w(0x0012)
    a.label('power_native')
    a.call(context_leave)
    a.w(0x6FA3)
    a.call(0x9690)
    a.goto(0x87D2)

    a.label('display_hook')
    a.call(context_enter)
    eligibility('display_native')
    a.call(redraw)
    a.call(context_leave)
    a.w(0x0012)
    a.label('display_native')
    a.call(context_leave)
    a.call(0x9690)
    a.goto(0x6DE2)

    a.label('idle_mode_hook')
    a.call(context_enter)
    eligibility('idle_mode_native')
    # Native MAN branch continues unchanged. Extend its native deadline to
    # TTL/DEF/AIR1, whose relative rows otherwise never pass the MAN gate.
    a.movff(s+1, 0xFE8)
    a.w(0x0900)
    a.goto('idle_mode_native', 'NZ')
    a.movff(s+3, 0xFE8)
    a.w(0x0A01)
    a.goto('idle_mode_native', 'NZ')
    a.movff(s+2, 0xFE8)
    a.w(0x0A01)
    a.goto('idle_mode_native', 'NZ')
    a.call(context_leave)
    a.goto(0x806E)
    a.label('idle_mode_native')
    a.call(context_leave)
    a.movff(0xD2, 0xFD9)
    a.movff(0xD3, 0xFDA)
    a.goto(0x806A)

    a.label('idle_expired_hook')
    a.call(context_enter)
    eligibility('idle_expired_native')
    a.call(idle_expired)
    a.w(0x0900)
    a.goto('idle_expired_native', 'NZ')
    # AIR1 can defer expiry while a relative TX plan is still pending. The
    # original deadline helper has already marked RAM54:55 as expired; do
    # not run the native8084..808A clear until the core accepts expiry.
    # AIR2 has no temporary relative display and keeps its native cleanup.
    a.movff(s+2, 0xFE8)
    a.w(0x0A01)
    a.goto('idle_expired_native', 'NZ')
    a.call(context_leave)
    a.goto(0x808E)
    a.label('idle_expired_native')
    a.call(context_leave)
    a.w(0x6BEC, 0x6BED, 0x6BEE)
    a.goto(0x8080)
    code = a.finish()
    hooks = []
    for address, label, resume in ((0x87CC, 'power_hook', 0x87D2),
                                   (0x6DDE, 'display_hook', 0x6DE2),
                                   (0x8062, 'idle_mode_hook', 0x806A),
                                   (0x807A, 'idle_expired_hook', 0x8080)):
        new = assembler.absolute(0xEF00, a.labels[label])
        new += bytes(len(preimages[address])//2 - len(new))
        hooks.append({'address': address, 'expected_hex': preimages[address],
                      'new_hex': new.hex(), 'role': 'sony_'+label,
                      'continuation': resume,
                      'evidence': 'complete instructions; original mode/deadline fallbacks replayed'})
    return {'sections': [{'address': base, 'data': code, 'role': 'sony_control_wrappers'}],
            'hooks': hooks, 'exports': a.labels,
            'reserved_ram': [{'start': step, 'end': step+1, 'owner': 'sony_original_power_delta'}],
            'required_imports': ['context_enter', 'context_leave', 'power_edit', 'redraw', 'idle_expired'],
            'unresolved_imports': [],
            'metadata': {'core_magic': 0xA8, 'normal_ui_guard': 'DD=0',
                         'idle_clock': 'existing native RAM54:55 deadline; no second timer',
                         'idle_retry': 'AIR1 core rejection resumes808E with expired native deadline intact; successful expiry or AIR2 follows8080 cleanup',
                         'hss_modified': False}}
