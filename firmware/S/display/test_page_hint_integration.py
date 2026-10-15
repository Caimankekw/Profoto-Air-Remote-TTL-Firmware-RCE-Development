#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Replay Sony page hints through linked gestures, original glyphs and LCD.

Only --out writes a report. No updater, USB or physical hardware is used.
Native GPIO pins are observation boundaries; native formatters, canonical
renderers, gesture callbacks and LCD serializer execute their machine code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT / 'shared'))
sys.dont_write_bytecode = True

import build_variants
from test_integrated_firmware import Machine, check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    profile_path = PROJECT / 'S' / 'port_profile.json'
    profile = json.loads(profile_path.read_text('utf-8'))
    check(profile.get('page_hint_on_chord') is True, 'Sony page callback disabled')
    check(profile.get('release_redraw') is True, 'Sony release callback disabled')
    linked = build_variants.link('S', profile)

    def new(mode, kind, page, selector):
        m = Machine('S', linked['image'], linked['mask'], profile, linked['components'], mode=mode)
        m.call('init')
        for offset, value in ((2, kind), (3, page), (4, selector), (5, 63), (6, 0x15)):
            m.set_state(offset, value)
        m.cpu.m[m.contract['selector']] = selector
        m.cpu.m[m.contract['head']] = 7
        m.cpu.m[m.contract['model']] = 5
        for group, target in enumerate((21, 32, 43, 54, 65, 76)):
            m.set_state(8 + group, target)
        m.call('redraw', group='backend')
        return m

    def lcd(m):
        return bytes(m.cpu.m[0x49:0x54])

    def native_first(m, first, tick):
        # Execute the installed original key-tail hook with the original
        # object pointer ABI rather than call the core's key entry directly.
        pointer = 0x125 if first == 1 else 0x12D
        m.secondary(first)
        m.tick(tick)
        m.cpu.m[0xAB:0xAD] = pointer.to_bytes(2, 'little')
        m.cpu.m[0xFE0] = 0
        m.cpu.run(0x8116)
        check(m.state(0x18) == 1, 'native key adapter did not start pending gesture')

    def serialized_bits(m):
        # Native Sony LCD context from the independent final-display test.
        for address, value in {0xD4: 0x9C, 0xD5: 1, 0x1A2: 0x7C, 0x1A3: 0xA1,
                               0x1A4: 0, 0x10A: 0, 0x10B: 8, 0x10C: 11,
                               0x10D: 11, 0x10E: 0, 0xE4: 0, 0xE5: 1}.items():
            m.cpu.m[address] = value
        bits, selects = [], []
        m.cpu.step_hooks[0x9F98] = lambda cpu: bits.append(cpu.w)
        m.cpu.step_hooks[0xA17C] = lambda cpu: selects.append((cpu.w, len(bits)))
        expected = []
        for part in (m.cpu.m[0x49:0x51], m.cpu.m[0x51:0x54]):
            expected.extend((1, 0, 1, 0, 0, 0, 0, 0, 0))
            for value in part:
                for pair in range(4):
                    expected.extend(((value >> (pair * 2)) & 1,
                                     (value >> (pair * 2 + 1)) & 1, 0, 0))
        for _ in range(60):
            m.cpu.m[0x73:0x75] = bytes((0x49, 0))
            m.cpu.m[0xFE0] = 0
            m.cpu.run(0x9E80)
            if (m.cpu.m[0x10D], m.cpu.m[0xE4], m.cpu.m[0xE5], m.cpu.m[0xE3]) == (11, 0, 1, 0):
                break
        else:
            raise AssertionError('native LCD serializer did not finish')
        check(bits == expected, 'native LCD serial data differs from hinted shadow')
        check(selects == [(2, 0), (1, 137), (0, 194)], 'native LCD selects changed')
        # Subsequent core calls use Machine's strict no-helper-replacement
        # guard. Retire only the documented GPIO observation boundaries.
        m.cpu.step_hooks.pop(0x9F98)
        m.cpu.step_hooks.pop(0xA17C)
        m.cpu.events.clear()
        return len(bits)

    cases = []
    for mode in (0, 1):
        for kind in (1, 2):
            for old_page in (0, 1):
                for selector in (1, 7):
                    for first in (1, 4):
                        m = new(mode, kind, old_page, selector)
                        target = old_page ^ 1
                        reference = new(mode, kind, target, selector)
                        normal_lcd = lcd(reference)
                        m.cpu.track_trace = True
                        native_first(m, first, 0)
                        m.secondary(5); m.tick(5); m.call('service')
                        m.tick(5 + profile['stable_counts']); m.call('service')
                        check(m.state(3) == target and m.state(0x18) == 2, 'page not toggled/latch absent')
                        hint = bytes(m.cpu.m[0x4A:0x50])
                        expected = bytes.fromhex('77003b000f00' if target == 0 else '7a001f001700')
                        check(hint == expected, 'real ABC/DEF glyphs absent after chord')
                        check(m.export('backend', 'page_hint') in m.cpu.trace, 'page callback not executed')
                        check(m.cpu.m[0xE3] == 1, 'hint did not schedule native LCD update')
                        # Final normal-UI hook reprojects only icons and must
                        # leave the numeric letter glyphs intact.
                        m.cpu.m[0xFE0] = 0
                        m.cpu.run(0x52DE, stops=(0x52E2,))
                        check(bytes(m.cpu.m[0x4A:0x50]) == hint, 'final icon hook erased page hint')
                        serial_count = serialized_bits(m)
                        for tick in (40, 100, 201):
                            m.tick(tick); m.call('service')
                            check(m.state(3) == target, 'held chord toggled repeatedly')
                        # One key still held must not unlock the chord.
                        m.secondary(1); m.tick(220); m.call('service')
                        m.tick(220 + profile['stable_counts']); m.call('service')
                        check(m.state(0x18) == 2, 'partial release unlocked chord')
                        m.secondary(0); m.tick(250); m.call('service')
                        m.tick(250 + profile['stable_counts']); m.call('service')
                        check(m.state(0x18) == 0, 'stable full release not cleared')
                        check(lcd(m) == normal_lcd, 'stable full release did not restore normal values')
                        check(m.cpu.m[0xE3] == 1, 'restored values not scheduled for LCD update')
                        # Repeated idle polls cannot reintroduce stale letters.
                        m.tick(400); m.call('service')
                        check(lcd(m) == normal_lcd, 'idle poll reintroduced letters')
                        cases.append({'mode': mode, 'manual_kind': kind,
                                      'old_page': old_page, 'selector': selector,
                                      'first_key': 'C' if first == 1 else 'HEAD',
                                      'hint_hex': hint.hex(), 'released_lcd_hex': normal_lcd.hex(),
                                      'native_serialized_bits': serial_count})

    # C+MODEL changes only manual policy, with no page letters. TTL swallows
    # it. Cancellation by another key also cannot issue a page hint.
    negative = []
    for mode in (0, 1):
        for raw in (3, 5):
            m = new(mode, 1, 0, 7)
            m.cpu.track_trace = True
            native_first(m, 1, 0)
            m.secondary(raw); m.tick(5)
            if raw == 5:
                m.cpu.m[0x11D] = 1  # Original A latest classifier sample.
            m.call('service'); m.tick(5 + profile['stable_counts']); m.call('service')
            check(m.state(3) == 0, 'negative path changed page')
            check(m.export('backend', 'page_hint') not in m.cpu.trace, 'non-page action displayed page letters')
            negative.append({'mode': mode, 'case': 'manual_chord' if raw == 3 else 'cancelled_page_chord'})

    result = {
        'status': 'PASS_SONY_LINKED_PAGE_HINT_LIFECYCLE',
        'image_sha256': hashlib.sha256(linked['image']).hexdigest(),
        'profile_sha256': hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        'code_end': hex(linked['code_end']),
        'page_chord_cases': len(cases), 'negative_cases': len(negative),
        'cases': cases, 'negative': negative,
        'scope': {'native_key_adapter': True, 'actual_linked_core': True,
                  'original_glyph_formatter': True, 'actual_lcd_serializer': True,
                  'physical_gpio_observed': False, 'updater_executed': False,
                  'device_boot_verified': False, 'hss_modified': False,
                  'native_redraw_may_end_hint_before_release': True},
    }
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
