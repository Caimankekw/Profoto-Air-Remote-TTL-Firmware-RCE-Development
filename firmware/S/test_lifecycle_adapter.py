#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Explicit import stubs test wrapper context/continuations, not core behavior."""
import importlib.util
import sys
from pathlib import Path
from lifecycle_adapter import construct, SAVE_REGISTERS

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_lifecycle_vm', HERE.parent/'shared/pic18_vm.py')
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)


def main():
    original = (HERE.parent/'shared/stock/S/original.base4000.partial.bin').read_bytes()
    component = construct(original, base=0xD000, state_base=0x680,
                          core_init=0xC000, core_service=0xC004)
    blob = bytearray(original)
    section = component['sections'][0]
    blob[section['address']-0x4000:section['address']-0x4000+len(section['data'])] = section['data']
    checks = 0
    for kind in ('init_wrapper', 'service_wrapper'):
        for seed in range(32):
            c = vm.CPU(blob)
            for address in SAVE_REGISTERS:
                c.write(address, (address*19+seed*23) & 255)
            c.m[0xFE0] &= 15
            expected = {address: c.read(address) for address in SAVE_REGISTERS}
            core_calls = []
            native_calls = []
            c.read_hooks[0xFF0] = lambda cpu: cpu.m[0xFF0]
            c.write_hooks[0xFF0] = lambda cpu, value: cpu.m.__setitem__(0xFF0, value)

            def destructive_import(cpu):
                core_calls.append(cpu.pc)
                for address in SAVE_REGISTERS:
                    cpu.write(address, 0)
                cpu.m[0x680:0x730] = b'\xA5'*0xB0

            def native_ui(cpu):
                native_calls.append(cpu.pc)
                # Native UI is allowed to alter context before the shared call.
                cpu.w = 0x31
                expected[0xFE8] = 0x31

            c.step_hooks[0xC000] = destructive_import
            c.step_hooks[0xC004] = destructive_import
            c.step_hooks[0x51DE] = native_ui
            result = c.run(component['exports'][kind], stops=(0x4E94,))
            assert len(core_calls) == 1
            assert len(native_calls) == int(kind == 'service_wrapper')
            if kind == 'init_wrapper':
                assert result == 0x4E94 and c.m[0x48] == 0 and c.m[0xFF0] & 8
                expected[0xFD8] = (expected[0xFD8] & ~4) | 4  # native CLRF sets Z
            for address, value in expected.items():
                assert c.read(address) == value, (kind, seed, hex(address), c.read(address), value)
            checks += 1
    print('PASS %d Sony lifecycle context/continuation cases; imports explicitly stubbed' % checks)


if __name__ == '__main__':
    main()
