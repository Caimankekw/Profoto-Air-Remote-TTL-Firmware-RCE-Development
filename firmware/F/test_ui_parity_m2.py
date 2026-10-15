#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay F M2 UI fixes through linked native PIC18 entry points.

Only --out writes a JSON evidence file. This does not build an installer, access
USB, replace native function bodies, or claim measured hardware timing.
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
from test_integrated_firmware import Machine


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def verify():
    profile = json.loads((HERE / 'port_profile.json').read_text('utf-8'))
    linked = build_variants.link('F', profile)
    components = linked['components']
    cases = []

    def new(mode=1, kind=1, page=0, selector=1):
        m = Machine('F', linked['image'], linked['mask'], profile, components, mode=mode)
        m.set_state(0x17f, 255)
        m.call('init')
        for offset, value in ((2, kind), (3, page), (4, selector), (5, 63)):
            m.set_state(offset, value)
        m.cpu.m[m.contract['selector']] = selector
        for address in (0xfe, 0x2b1, 0x1da, 0x1e0):
            m.cpu.m[address] = 0x71
        return m

    def expiry(m, tick):
        m.tick(tick)
        m.cpu.m[0xfe0] = 0
        m.cpu.track_trace = True
        m.cpu.trace.clear()
        irq_before = bytes(m.cpu.m[a] for a in (0xfe, 0x2b1, 0x1da, 0x1e0))
        m.cpu.run(0x8618, stops=(0x8644,))
        check(not any(e[0] == 'step_hook' for e in m.cpu.events), 'native helper replacement')
        check(bytes(m.cpu.m[a] for a in (0xfe, 0x2b1, 0x1da, 0x1e0)) == irq_before,
              'idle hook changed ISR-owned state')
        return m.export('core', 'idle_expired') in m.cpu.trace

    def activity(m, tick=100):
        m.tick(tick)
        m.cpu.m[0xea:0xec] = (0x12a).to_bytes(2, 'little')
        m.cpu.m[0xfe0] = 0
        m.cpu.run(0x5e6a)
        return int.from_bytes(m.cpu.m[0xa6:0xa8], 'little')

    def power(m, tick=1400):
        m.tick(tick)
        m.cpu.m[0xfe0] = 0
        m.cpu.w = 1
        m.cpu.run(0x8d7e)

    # Actual press -> actual power -> original native mode gate and timer.
    # Keep TTL ABC FEC and AIR2 absolute values resident across native expiry.
    for mode in (0, 1):
        for kind in (1, 2):
            for page in (0, 1):
                for selector in (1, 2, 3, 7):
                    m = new(mode, kind, page, selector)
                    deadline = activity(m)
                    check(deadline == 1600, 'original activity deadline changed')
                    power(m)
                    m.service_until_idle()
                    before = (m.state(7), m.state(14, 6))
                    protected = (m.state(8, 6), m.state(20, 3), m.state(5, 2), tuple(m.frames))
                    check(not expiry(m, 1599), 'idle clear ran before original expiry')
                    check((m.state(7), m.state(14, 6)) == before, 'relative state changed early')
                    called = expiry(m, 1601)
                    admitted = mode == 1 or (page == 1 and kind == 1)
                    check(called == admitted, 'wrong TTL/MAN native gate admission')
                    if admitted and kind == 1:
                        check(m.state(7) == 0 and m.state(14, 6) == bytes(6), 'AIR1 clear missing')
                    else:
                        check((m.state(7), m.state(14, 6)) == before, 'non-relative state cleared')
                    check((m.state(8, 6), m.state(20, 3), m.state(5, 2), tuple(m.frames)) == protected,
                          'expiry changed targets/FEC/masks/radio frames')
                    actual_deadline = int.from_bytes(m.cpu.m[0xa6:0xa8], 'little')
                    check(actual_deadline == (0 if admitted else deadline), 'native deadline reset changed')
                    cases.append(dict(test='native_idle_matrix', mode=mode, kind=kind,
                                      page=page, selector=selector, expired_hook=called,
                                      deadline_after=actual_deadline))

    # The box map comes from this firmware's stock helper, not a Canon bitmap.
    controls = {}
    for selector in (1, 2, 3, 7):
        m = new(selector=selector)
        m.cpu.m[0x87] = 0xff
        m.cpu.m[0xfe0] = 0
        m.cpu.run(0x880e)
        controls[selector] = m.cpu.m[0x87] & 0x2a
    check(controls == {1: 2, 2: 8, 3: 32, 7: 0}, 'stock F box mapping changed')
    expected = dict(controls)
    expected[7] = controls[1] | controls[2] | controls[3]
    for mode in (0, 1):
        for kind in (1, 2):
            for page in (0, 1):
                for selector in (1, 2, 3, 7):
                    m = new(mode, kind, page, selector)
                    masks_before = (m.cpu.m[0x29], m.cpu.m[0x38], m.state(5, 2))
                    for _ in range(2):
                        m.cpu.m[0xfe0] = 0
                        m.cpu.run(0x742e)
                    check(m.cpu.m[0x87] & 0x2a == expected[selector], 'row/ALL boxes mismatch')
                    check(m.cpu.m[0x87] & 0x15 == (0x15 if page == 0 else 0), 'page labels changed')
                    check((m.cpu.m[0x29], m.cpu.m[0x38], m.state(5, 2)) == masks_before,
                          'render changed group masks')
                    check(m.cpu.m[0x94] == 0, 'render enqueued RF')
                    cases.append(dict(test='native_display_matrix', mode=mode, kind=kind,
                                      page=page, selector=selector, box_bits=m.cpu.m[0x87] & 0x2a))

    # A transaction spanning expiry must not consume the only deadline before
    # relative values can clear. Include the stock 15-bit clock wrap boundary.
    for mode, page in ((1, 0), (1, 1), (0, 1)):
        for start in (100, 32000):
            m = new(mode, 1, page)
            deadline = activity(m, start)
            check(deadline == ((start + 1500) & 0x7fff), 'native wrapped deadline')
            power(m, (deadline - 100) & 0x7fff)
            check(m.state(0x28) != 0 and m.state(7) != 0, 'pending AIR1 precondition')
            before = (m.state(7), m.state(14, 6))
            check(expiry(m, (deadline + 1) & 0x7fff), 'pending expiry did not enter core')
            check((m.state(7), m.state(14, 6)) == before, 'pending expiry cleared transaction state')
            check(int.from_bytes(m.cpu.m[0xa6:0xa8], 'little') == 0xffff,
                  'deferred expiry lost the native expired latch')
            m.service_until_idle()
            check(m.state(0x28) == 0, 'pending transaction did not drain')
            check(expiry(m, (deadline + 10) & 0x7fff), 'deferred expiry failed to retry')
            check(m.state(7) == 0 and m.state(14, 6) == bytes(6), 'drained AIR1 did not clear')
            check(m.cpu.m[0xa6:0xa8] == bytes(2), 'successful expiry did not reset native deadline')
            cases.append(dict(test='pending_expiry_retry', mode=mode, page=page,
                              activity_tick=start, deadline=deadline, crosses_wrap=start == 32000))

    for page in (0, 1):
        m = new(1, 2, page)
        deadline = activity(m)
        power(m)
        check(m.state(0x28) != 0, 'pending AIR2 precondition')
        targets = m.state(8, 6)
        expiry(m, 1601)
        check(m.cpu.m[0xa6:0xa8] == bytes(2), 'AIR2 expiry unnecessarily retries forever')
        check(m.state(8, 6) == targets, 'AIR2 expiry changed absolute targets')
        cases.append(dict(test='pending_air2_consumes_native_expiry', page=page))

    # Readiness must be refreshed inside the shared idle handler. An old idle
    # snapshot must not authorize redraw once a native camera/queue/IRQ gate
    # becomes busy. These are the exact F native_idle gates, not a generic
    # claim about all hardware interrupts or physical camera timing.
    native_busy_values = ((0x7a, 1), (0x28, 1), (0x61, 1), (0x85, 1),
                          (0x94, 17), (0x3a, 0), (0xfa4, 0x80),
                          (0xff0, 2), (0xff0, 4))
    for mode, page in ((1, 0), (1, 1), (0, 1)):
        for address, busy_value in native_busy_values:
            m = new(mode, 1, page)
            m.set_state(7, 1 << (3 * page))
            m.set_state(14 + 3 * page, 5)
            m.call('read_inputs', group='backend')
            check(m.state(0x77) & 1, 'idle readiness precondition')
            m.cpu.m[0xa6:0xa8] = (1600).to_bytes(2, 'little')
            saved_native = m.cpu.m[address]
            m.cpu.m[address] = busy_value
            before = (m.state(7), m.state(14, 6))
            check(expiry(m, 1601), 'busy expiry did not enter shared gate')
            check((m.state(7), m.state(14, 6)) == before, 'busy native gate allowed clear')
            check(m.export('backend', 'redraw') not in m.cpu.trace, 'busy native gate allowed redraw')
            check(m.cpu.m[0xa6:0xa8] == b'\xff\xff', 'busy native gate lost expiry latch')
            m.cpu.m[address] = saved_native
            check(expiry(m, 1610), 'ready native gate did not retry')
            check(m.state(7) == 0 and m.state(14, 6) == bytes(6), 'ready native gate did not clear')
            check(m.cpu.m[0xa6:0xa8] == bytes(2), 'ready native gate did not finish timer')
            cases.append(dict(test='fresh_native_busy_retry', mode=mode, page=page,
                              native_address=hex(address), busy_value=busy_value))

    # Startup/uninitialized fallback still follows the stock native MAN gate.
    for mode in (0, 1):
        m = new(mode, 1, 1)
        m.set_state(0, 0)
        m.cpu.m[0xa6:0xa8] = (1600).to_bytes(2, 'little')
        called = expiry(m, 1601)
        check(not called, 'uninitialized state called AIR2 core')
        check(int.from_bytes(m.cpu.m[0xa6:0xa8], 'little') == (1600 if mode == 0 else 0),
              'uninitialized stock gate changed')
        cases.append(dict(test='uninitialized_native_gate_fallback', mode=mode))

    original = (PROJECT / 'shared/stock/F/original.base4000.partial.bin').read_bytes()
    allowed = set()
    for component in components.values():
        for section in component['sections']:
            allowed.update(range(section['address'] - 0x4000,
                                 section['address'] - 0x4000 + len(section['data'])))
        for hook in component.get('hooks', []):
            allowed.update(range(hook['address'] - 0x4000,
                                 hook['address'] - 0x4000 + len(bytes.fromhex(hook['new_hex']))))
    changed = {i for i, pair in enumerate(zip(original, linked['image'])) if pair[0] != pair[1]}
    check(changed <= allowed, 'change outside declared AIR2 code/hooks')
    cases.append(dict(test='stock_outside_declared_air2_patch_unchanged', changed_bytes=len(changed)))
    counts = {}
    for case in cases:
        counts[case['test']] = counts.get(case['test'], 0) + 1
    return dict(status='PASS', model='F', cases=len(cases), counts=counts,
                image_sha256=hashlib.sha256(linked['image']).hexdigest(),
                native_idle_entry='0x8618', native_display_entry='0x742E',
                local_native_box_controls=controls, results=cases,
                source_sha256={str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (HERE / 'native_hooks.py', HERE / 'native_backend.py', Path(__file__))},
                scope=dict(actual_linked_machine_code=True, native_function_stubs=0,
                           hardware_accessed=False, installers_executed=False,
                           physical_timer_calibration=False,
                           boundaries=['explicit idle MMIO fixture', 'declared NVM controller model',
                                       'downstream queue consumption fixture; not physical RF completion']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    report = verify()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'model', 'cases', 'counts', 'image_sha256')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
