#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Sony A6 lifecycle trampolines. Component only; never a flashable image.

The caller supplies proved SRAM and fully resolved shared-core imports.
Provider offsets B0..115 are reserved for the foreground native context.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_lifecycle_asm', HERE/'display/display_adapter.py')
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)

SAVE_REGISTERS = tuple(range(0x6B, 0xC1)) + (
    0xFE9, 0xFEA, 0xFE1, 0xFE2, 0xFD9, 0xFDA,
    0xFF3, 0xFF4, 0xFF5, 0xFF6, 0xFF7, 0xFF8,
    0xFE8, 0xFD8, 0xFE0,
)


def construct(original, *, base, state_base, core_init, core_service):
    if base & 1 or base < 0xAF80:
        raise ValueError('Sony lifecycle must be placed beyond original code')
    if state_base < 0x464 or state_base + 0x180 > 0xF00:
        raise ValueError('caller must prove a disjoint 384-byte SRAM allocation')
    for entry in (core_init, core_service):
        if type(entry) is not int or entry & 1 or not 0xAF80 <= entry < 0xF800:
            raise ValueError('resolved shared-core import required')
    for address, expected in ((0x4E90, '486af086'), (0x4EC0, 'efec28f0')):
        if original[address-0x4000:address-0x4000+4] != bytes.fromhex(expected):
            raise ValueError('Sony native lifecycle preimage mismatch')
    a = assembler.Asm(base)
    # Fixed-width two-pass layout: startup20B, foreground18B, then helpers.
    context_enter = base + 38
    context_leave = context_enter + len(SAVE_REGISTERS) * 4 + 2
    for name, native_before, core, continuation in (
            ('init_wrapper', False, core_init, 0x4E94),
            ('service_wrapper', True, core_service, None)):
        a.label(name)
        if native_before:
            a.call(0x51DE)
        a.call(context_enter)
        a.call(core)
        a.call(context_leave)
        if continuation:
            a.w(0x6A48, 0x86F0)  # replay CLRF48, BSF INTCON3,3
            a.goto(continuation)
        else:
            a.w(0x0012)
    a.label('context_enter')
    if a.labels['context_enter'] != context_enter:
        raise ValueError('fixed lifecycle layout changed')
    for offset, address in enumerate(SAVE_REGISTERS):
        a.movff(address, state_base + 0xB0 + offset)
    a.w(0x0012)
    a.label('context_leave')
    if a.labels['context_leave'] != context_leave:
        raise ValueError('fixed lifecycle layout changed')
    for offset, address in enumerate(SAVE_REGISTERS):
        a.movff(state_base + 0xB0 + offset, address)
    a.w(0x0012)
    code = a.finish()
    return {
        'sections': [{'address': base, 'data': code, 'role': 'sony_lifecycle'}],
        'hooks': [
            {'address': 0x4E90, 'expected_hex': '486af086',
             'new_hex': assembler.absolute(0xEF00, a.labels['init_wrapper']).hex(),
             'role': 'sony_init_once', 'continuation': 0x4E94,
             'evidence': '4ED0 loop branches to4E94, never reenters startup4E90'},
            {'address': 0x4EC0, 'expected_hex': 'efec28f0',
             'new_hex': assembler.absolute(0xEC00, a.labels['service_wrapper']).hex(),
             'role': 'sony_foreground_service', 'continuation': 0x4EC4,
             'evidence': 'replay native51DE before shared service; original IRQ/HSS calls retained'},
        ],
        'exports': a.labels,
        'reserved_ram': [{'start': state_base+0xB0,
                          'end': state_base+0xB0+len(SAVE_REGISTERS),
                          'owner': 'sony_outer_context'}],
        'required_imports': ['core_init', 'core_service'], 'unresolved_imports': [],
        'metadata': {
            'saved_native_registers': SAVE_REGISTERS,
            'forbidden_reentry': 'core/backend must not call native51DE or these lifecycle wrappers',
            'irq_behavior': 'no interrupt-mask, priority, or HSS instruction changes',
            'not_a_hardware_timing_proof': True,
        },
    }
