#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Execute Sony control hooks, lifecycle save helpers and original 9690.

Only the shared-core callbacks are explicit destructive ABI test doubles.
This verifies guards, arguments, context and exact native continuations; it
does not establish shared-core policy, RF behavior or physical timing.
"""
import importlib.util
import sys
from pathlib import Path

from control_adapter import construct
from lifecycle_adapter import construct as lifecycle_construct, SAVE_REGISTERS

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_control_vm', HERE.parent/'shared/pic18_vm.py')
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)

S = 0x680
CORE_POWER, CORE_REDRAW, CORE_IDLE = 0xC000, 0xC004, 0xC008


def main():
    original = (HERE.parent/'shared/stock/S/original.base4000.partial.bin').read_bytes()
    lifecycle = lifecycle_construct(original, base=0xD000, state_base=S,
                                    core_init=0xC00C, core_service=0xC010)
    options = dict(base=0xD400, state_base=S,
                   context_enter=lifecycle['exports']['context_enter'],
                   context_leave=lifecycle['exports']['context_leave'],
                   power_edit=CORE_POWER, redraw=CORE_REDRAW, idle_expired=CORE_IDLE)
    component = construct(original, **options)
    image = bytearray(original)
    for part in (lifecycle, component):
        for section in part['sections']:
            offset = section['address'] - 0x4000
            image[offset:offset+len(section['data'])] = section['data']
    for hook in component['hooks']:
        offset = hook['address'] - 0x4000
        expected = bytes.fromhex(hook['expected_hex'])
        new = bytes.fromhex(hook['new_hex'])
        assert original[offset:offset+len(expected)] == expected
        assert len(new) == len(expected)
        image[offset:offset+len(new)] = new

    def new_cpu(blob=image, *, seed=0, magic=0xA8, dd=0, mode=0,
                page=0, manual=1, step=1):
        c = vm.CPU(blob)
        for address in range(0x464):
            c.m[address] = (address * 19 + seed * 23) & 255
        for address in SAVE_REGISTERS:
            c.write(address, (address * 7 + seed * 13) & 255)
        c.m[0xFE0] = 0  # Native callers enter with bank zero.
        c.m[0xD2], c.m[0xD3], c.m[0x193] = 0x93, 1, mode
        c.m[0xDD] = dd
        c.m[S], c.m[S+1], c.m[S+2], c.m[S+3] = magic, mode, manual, page
        c.w = step
        c.track_trace = True
        return c

    def native_context(c):
        return bytes(c.m[:0x464]), tuple(c.read(a) for a in SAVE_REGISTERS)

    def install_callback(c, address, result=1):
        calls = []

        def callback(cpu):
            calls.append((cpu.pc, cpu.w))
            # Simulate the shared core and its native helper calls clobbering
            # every register which the outer Sony context promises to save.
            for reg in SAVE_REGISTERS:
                cpu.write(reg, 0)
            cpu.w = result

        c.step_hooks[address] = callback
        return calls

    cases = {'power_delta_and_rejection': 0, 'power_native_fallback': 0,
             'display_guard_and_context': 0, 'idle_mode_branches': 0,
             'idle_expired_context': 0, 'idle_deferred_context': 0, 'preimage_rejection': 0}

    # All byte deltas, including negative +/-10 encodings and zero. A core
    # rejection must remain rejected; never fall through to the native sender.
    for step in range(256):
        for result in (0, 1):
            c = new_cpu(step=step, seed=step % 17)
            before = native_context(c)
            calls = install_callback(c, CORE_POWER, result)
            c.run(0x87CC, stops=(0x87D2,))
            assert calls == [(CORE_POWER, step)], (step, result, calls)
            assert 0x87D2 not in c.trace and 0x9690 not in c.trace
            assert native_context(c) == before, (step, result, 'context')
            assert c.m[S+0x116] == step
            cases['power_delta_and_rejection'] += 1

    # Exhaust both exact-magic and normal-UI guards. Native mode helper 9690
    # executes without a stub and its Z, W, FSR2 side effects match stock.
    guards = [(m, 0) for m in range(256) if m != 0xA8]
    guards += [(0xA8, dd) for dd in range(1, 256)]
    for i, (magic, dd) in enumerate(guards):
        mode, step = i % 2, (i * 37) & 255
        c = new_cpu(magic=magic, dd=dd, mode=mode, step=step, seed=i % 13)
        golden = new_cpu(original, magic=magic, dd=dd, mode=mode, step=step, seed=i % 13)
        calls = install_callback(c, CORE_POWER)
        assert c.run(0x87CC, stops=(0x87D2,)) == 0x87D2
        golden.run(0x87CC, stops=(0x87D2,))
        assert not calls and 0x9690 in c.trace
        assert native_context(c) == native_context(golden), (magic, dd, 'power fallback')
        assert c.m[0xA3] == step and c.w == mode
        assert bool(c.m[0xFD8] & vm.Z) == (mode == 0)
        cases['power_native_fallback'] += 1

    for magic, dd in [(0xA8, 0)] + guards:
        for mode in (0, 1):
            c = new_cpu(magic=magic, dd=dd, mode=mode, seed=(magic+dd) % 11)
            before = native_context(c)
            calls = install_callback(c, CORE_REDRAW)
            c.run(0x6DDE, stops=(0x6DE2,))
            if magic == 0xA8 and dd == 0:
                assert len(calls) == 1 and 0x9690 not in c.trace
                assert native_context(c) == before
            else:
                golden = new_cpu(original, magic=magic, dd=dd, mode=mode, seed=(magic+dd) % 11)
                golden.run(0x6DDE, stops=(0x6DE2,))
                assert not calls and 0x9690 in c.trace
                assert native_context(c) == native_context(golden)
            cases['display_guard_and_context'] += 1

    # The extension skips only the original MAN gate in TTL/DEF/AIR1. All
    # other combinations replay the exact original MOVFF pair before 806A.
    for magic in (0, 0xA7, 0xA8, 0xFF):
        for dd in (0, 1, 0xFF):
            for mode in (0, 1, 2):
                for page in (0, 1, 2):
                    for manual in (0, 1, 2):
                        c = new_cpu(magic=magic, dd=dd, mode=mode, page=page, manual=manual)
                        before = native_context(c)
                        special = magic == 0xA8 and dd == 0 and mode == 0 and page == 1 and manual == 1
                        endpoint = c.run(0x8062, stops=(0x806A, 0x806E))
                        assert endpoint == (0x806E if special else 0x806A)
                        if special:
                            assert native_context(c) == before
                        else:
                            golden = new_cpu(original, magic=magic, dd=dd, mode=mode, page=page, manual=manual)
                            golden.run(0x8062, stops=(0x806A,))
                            assert native_context(c) == native_context(golden)
                            assert c.get_fsr(2) == 0x193
                        assert not any(a in c.trace for a in (CORE_POWER, CORE_REDRAW, CORE_IDLE))
                        cases['idle_mode_branches'] += 1

    for magic in (0, 0xA7, 0xA8, 0xFF):
        for dd in (0, 1, 0xFF):
            for seed in range(16):
                c = new_cpu(magic=magic, dd=dd, seed=seed)
                calls = install_callback(c, CORE_IDLE)
                golden = new_cpu(original, magic=magic, dd=dd, seed=seed)
                assert c.run(0x807A, stops=(0x8080,)) == 0x8080
                golden.run(0x807A, stops=(0x8080,))
                assert len(calls) == int(magic == 0xA8 and dd == 0)
                assert c.m[0xEC:0xEF] == b'\0\0\0'
                assert native_context(c) == native_context(golden)
                cases['idle_expired_context'] += 1

    # A rejected AIR1 expiry returns to the original after-idle continuation
    # without clearing native relative state or its expired deadline. AIR2
    # still takes normal cleanup even though it has no relative expiry.
    for manual in (1, 2):
        for seed in range(16):
            c = new_cpu(manual=manual, seed=seed)
            before = native_context(c)
            install_callback(c, CORE_IDLE, result=0)
            endpoint = c.run(0x807A, stops=(0x8080, 0x808E))
            assert endpoint == (0x808E if manual == 1 else 0x8080)
            if manual == 1:
                assert native_context(c) == before
            else:
                golden = new_cpu(original, manual=manual, seed=seed)
                golden.run(0x807A, stops=(0x8080,))
                assert native_context(c) == native_context(golden)
            cases['idle_deferred_context'] += 1

    for hook in component['hooks']:
        raw = bytes.fromhex(hook['expected_hex'])
        for delta in range(len(raw)):
            changed = bytearray(original)
            changed[hook['address']-0x4000+delta] ^= 1
            try:
                construct(changed, **options)
            except ValueError as exc:
                assert 'preimage' in str(exc)
            else:
                raise AssertionError('mutated hook byte accepted')
            cases['preimage_rejection'] += 1

    print('PASS %d Sony control hook cases: %s' % (sum(cases.values()), cases))
    print('Native 9690 and lifecycle context helpers execute actual instructions; only core callbacks are stubbed.')


if __name__ == '__main__':
    main()
