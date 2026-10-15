#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay Sony A6 journal geometry, without flash erase/program or hardware I/O.

These tests execute original instructions. They establish logical addresses,
not physical erase geometry; no MCU is assumed from Canon's implementation.
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STOCK = HERE.parent / 'shared/stock/S'
IMAGE = (STOCK / 'original.base4000.partial.bin').read_bytes()
spec = importlib.util.spec_from_file_location(
    'sony_nvm_vm', HERE.parent / 'shared/pic18_vm.py')
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)


def init_descriptor(record_size=4, slot_count=0, end=0x1FBFF):
    c = vm.CPU(IMAGE, {0x6B: 0xA5, 0x6C: 1, 0x71: slot_count, 0x72: record_size})
    c.m[0x6D:0x71] = end.to_bytes(4, 'little')
    c.run(0x835E)
    expected = end.to_bytes(4, 'little') + bytes((slot_count, 0, (record_size + 1) & 0xFE))
    assert bytes(c.m[0x1A5:0x1AC]) == expected
    assert not getattr(c, 'events', [])
    return c


def main():
    cases = 0
    for width in range(1, 255):
        for slots in (0, 1, 63, 255):
            init_descriptor(width, slots)
            cases += 1
    slots = []
    for index in range(256):
        c = init_descriptor()
        c.m[0x6B:0x6E] = bytes((0xA5, 1, index))
        c.run(0x81A6)
        actual = int.from_bytes(c.m[0x6B:0x6F], 'little')
        expected = 0x1FBFF - index * 4
        assert actual == expected, (index, hex(actual), hex(expected))
        assert not getattr(c, 'events', [])
        slots.append({'index': index, 'first_byte': expected - 3, 'last_byte': expected})
        cases += 1
    report = {
        'result': 'PASS', 'real_original_instruction_cases': cases,
        'scope': 'Logical descriptor and address arithmetic only; no flash writes or hardware',
        'constructor': '835E', 'address_function': '81A6',
        'original_descriptor': {'ram': '01A5..01AB', 'end': '01FBFF', 'slot_count_byte': 0,
                                'effective_slot_count': 256, 'record_bytes': 4},
        'original_logical_page': ['01F800', '01FC00'],
        'flash_write_entry': '9840', 'flash_erase_entry': '9FE4',
        'interrupt_caveat': 'Both helpers unconditionally set FD0 bit7 and FF2 bit7 on return',
        'physical_erase_page_size_proven': False,
        'new_persistence_address_allocated': None,
        'slot_examples': slots[:2] + slots[-2:],
    }
    (HERE / 'sony_nvm_evidence.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('PASS %d Sony native journal arithmetic cases; no flash operations' % cases)


if __name__ == '__main__':
    main()
