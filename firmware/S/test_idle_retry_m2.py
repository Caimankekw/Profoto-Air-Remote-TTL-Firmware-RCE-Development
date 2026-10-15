#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Replay native Sony idle gate/deadline/cleanup on the linked M2 image.

The pending transaction flag is seeded explicitly; this verifies cleanup and
retry, not real radio timing. No native function is replaced by a test stub.
Only --out writes a report. No updater or USB access is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / 'shared'))
sys.dont_write_bytecode = True
import build_variants
from test_integrated_firmware import Machine, check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    profile_path = HERE / 'port_profile.json'
    profile = json.loads(profile_path.read_text('utf-8'))
    linked = build_variants.link('S', profile)

    def new(mode, page, kind=1, pending=0):
        m = Machine('S', linked['image'], linked['mask'], profile, linked['components'], mode=mode)
        m.call('init')
        for offset, value in ((2, kind), (3, page), (4, 1), (5, 63), (7, 1 << (page*3)),
                              (0x0E + page*3, 10), (0x28, pending)):
            m.set_state(offset, value)
        m.cpu.m[m.contract['selector']] = 1
        m.cpu.m[0x54:0x56] = (1600).to_bytes(2, 'little')
        m.cpu.m[0xEC:0xEF] = b'\x0a\x0b\x0c'
        m.cpu.track_trace = True
        return m

    def snapshot(m):
        return {'visible': m.state(7), 'relative_hex': m.state(14, 6).hex(),
                'deadline': int.from_bytes(m.cpu.m[0x54:0x56], 'little'),
                'native_relative_hex': bytes(m.cpu.m[0xEC:0xEF]).hex(),
                'pending': m.state(0x28),
                'idle_called': m.export('core', 'idle_expired') in m.cpu.trace}

    def idle(m, tick):
        m.tick(tick); m.cpu.m[0xFE0] = 0; m.cpu.trace.clear()
        check(m.cpu.run(0x8062, stops=(0x808E,)) == 0x808E, 'native idle continuation')
        check(not any(event[0] == 'step_hook' for event in m.cpu.events), 'native helper replacement')
        check(not m.flash.operations, 'idle path wrote flash')
        return snapshot(m)

    cases = []
    # Original mode gate must be used: MAN on either page and the supported
    # TTL DEF/AIR1 extension. Verify the next native poll retries after busy.
    for mode, page in ((1, 0), (1, 1), (0, 1)):
        for pending in (0, 1, 2, 3):
            m = new(mode, page, pending=pending)
            before = snapshot(m)
            early = idle(m, 1599)
            check(not early['idle_called'] and early['deadline'] == 1600, 'early expiry')
            first = idle(m, 1601)
            check(first['idle_called'], 'real upstream mode/deadline gate bypassed core')
            if pending:
                check(first['deadline'] == 65535, 'busy expiry lost native expired sentinel')
                check(first['visible'] == before['visible'] and
                      first['relative_hex'] == before['relative_hex'], 'busy cleared canonical values')
                check(first['native_relative_hex'] == before['native_relative_hex'], 'busy cleared native values')
                repeated = idle(m, 1650)
                check(repeated['deadline'] == 65535 and repeated['visible'] == before['visible'], 'busy retry consumed deadline')
            else:
                check(first['deadline'] == 0 and first['visible'] == 0, 'idle expiry not committed')
            m.set_state(0x28, 0)
            after = idle(m, 1700)
            check(after['deadline'] == 0 and after['visible'] == 0 and
                  after['relative_hex'] == '000000000000', 'retry did not expire values')
            check(after['idle_called'] == bool(pending), 'next native poll retry mismatch')
            check(after['native_relative_hex'] == '000000', 'normal native relative cleanup missing')
            final = idle(m, 1800)
            check(not final['idle_called'], 'cleaned deadline kept retriggering')
            cases.append({'mode': mode, 'page': page, 'pending': pending,
                          'before': before, 'first_expiry': first, 'after_pending_cleared': after})

    negative = []
    for mode, page, kind in ((1, 0, 2), (1, 1, 2), (0, 0, 1), (0, 0, 2), (0, 1, 2)):
        for pending in (0, 1):
            m = new(mode, page, kind, pending)
            before = snapshot(m)
            first = idle(m, 1601)
            check(first['visible'] == before['visible'] and
                  first['relative_hex'] == before['relative_hex'], 'non-AIR1 values cleared')
            # MAN AIR2 keeps the original native timeout cleanup; TTL FEC
            # and TTL DEF/AIR2 remain excluded by the original mode gate.
            check(first['deadline'] == (0 if mode else 1600), 'negative path deadline policy changed')
            check(first['idle_called'] == bool(mode), 'negative path core admission changed')
            negative.append({'mode': mode, 'page': page, 'kind': kind, 'pending': pending, 'after': first})

    transitions = []
    for old_mode in (0, 1):
        m = new(old_mode, 1, pending=1)
        first = idle(m, 1601)
        check(first['deadline'] == 65535, 'transition precondition')
        m.cpu.m[m.contract['mode']] = old_mode ^ 1
        # Native mode change invalidates the old TX plan in real core.service.
        # Hold another native key to exclude unrelated NVM saving.
        m.cpu.m[0x11D] = 1
        m.call('service')
        m.cpu.m[0x11D] = 0
        check(m.state(1) == (old_mode ^ 1) and m.state(0x28) == 0, 'mode transition not reconciled')
        after = idle(m, 1700)
        check(after['deadline'] == 0 and after['visible'] == 0, 'mode transition stranded deadline')
        transitions.append({'from_mode': old_mode, 'to_mode': old_mode ^ 1, 'after': after})

    native_busy = []
    protected = (0x193, 0x194, 0xDB, 0xF3, 0x197, 0x198, 0x199,
                 0xE6, 0xE7, 0xE8, 0xFF2, 0xFD0, 0xFF0, 0xF98, 0xFA4)
    for mode, page in ((1, 0), (1, 1), (0, 1)):
        for busy_address, busy_value in ((0xDC, 1), (0xD1, 0x80),
                                         (0x194, 1), (0xE8, 17),
                                         (0xF98, 0x10), (0xFF0, 1)):
            m = new(mode, page)
            m.call('redraw', group='backend')
            initial = snapshot(m)
            saved_busy = m.cpu.m[busy_address]
            m.cpu.m[busy_address] = busy_value
            canary = {address: m.cpu.m[address] for address in protected}
            # Seed a stale ready snapshot; only the fresh backend call can
            # discover that the original Sony edit gate is now busy.
            m.set_state(0x77, 0x87)
            shown = bytes(m.cpu.m[0x49:0x54])
            first = idle(m, 1601)
            check(first['idle_called'] and first['deadline'] == 65535, 'native busy consumed idle deadline')
            check(first['visible'] == initial['visible'] and
                  first['relative_hex'] == initial['relative_hex'], 'native busy cleared relative state')
            check(bytes(m.cpu.m[0x49:0x54]) == shown, 'native busy redrew canonical LCD')
            check(all(m.cpu.m[address] == value for address, value in canary.items()), 'idle altered camera/IRQ/queue state')
            m.cpu.m[busy_address] = saved_busy
            if busy_address in canary:
                canary[busy_address] = saved_busy
            after = idle(m, 1700)
            check(after['idle_called'] and after['deadline'] == 0 and after['visible'] == 0,
                  'native busy-to-ready did not retry')
            check(all(m.cpu.m[address] == value for address, value in canary.items()), 'retry altered camera/IRQ/queue state')
            native_busy.append({'mode': mode, 'page': page, 'busy_register': hex(busy_address),
                                'busy_value': busy_value, 'first_expiry': first,
                                'after_ready': after, 'protected_registers_unchanged': True})

    report = {'status': 'PASS_SONY_M2_NATIVE_IDLE_RETRY',
              'image_sha256': hashlib.sha256(linked['image']).hexdigest(),
              'profile_sha256': hashlib.sha256(profile_path.read_bytes()).hexdigest(),
              'code_end': hex(linked['code_end']),
              'retry_cases': len(cases), 'negative_cases': len(negative),
              'mode_transition_cases': len(transitions), 'cases': cases,
              'negative': negative, 'mode_transitions': transitions,
              'native_busy_retry_cases': len(native_busy), 'native_busy_retries': native_busy,
              'scope': {'native_entry': '0x8062', 'native_stop': '0x808E',
                        'native_expired_sentinel': '0xFFFF at RAM54:55',
                        'native_deadline_helper': '0x7316',
                        'native_deadline_clear': '0xAD3E via0x808A',
                        'helper_replacements': 0, 'radio_busy_seeded': True,
                        'hss_changed': False, 'hardware_accessed': False}}
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
