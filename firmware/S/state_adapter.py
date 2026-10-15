#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Sony A6 native state snapshot/projection for the shared AIR2 core.

No RF or NVM operation is performed here. Native state projection uses a
bounded GIEH/GIEL critical section; it never restores a whole interrupt register
or modifies pending flags/IPEN. Quiet predicates must be supplied explicitly.
"""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_state_asm', HERE/'display/display_adapter.py')
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)

SECONDARY_KEYS = ((0x125, 0), (0x129, 1), (0x12D, 2))
OTHER_KEYS = (0x115, 0x119, 0x11D, 0x121, 0x131, 0x135, 0x139, 0x13D)


def construct(original, *, base, state_base, radio_quiet, nvm_quiet=None):
    if base & 1 or base < 0xAF80:
        raise ValueError('Sony component must be outside original code')
    if not 0x464 <= state_base or state_base + 0x180 > 0xF00:
        raise ValueError('explicit proved extension SRAM required')
    for entry in (radio_quiet,) + ((nvm_quiet,) if nvm_quiet is not None else ()):
        if type(entry) is not int or entry & 1 or not 0xAF80 <= entry < 0xF800:
            raise ValueError('resolved native quiet predicate required')
    s = state_base
    flags = s + 0x115
    saved_irq = s + 0x118
    accepted = s + 0x119
    a = assembler.Asm(base)

    def put(value, dest):
        a.w(0x0E00 | value)
        a.movff(0xFE8, dest)

    def load(addr):
        a.movff(addr, 0xFE8)

    def setbit(addr, bit):
        a.w(0x0100 | (addr >> 8), 0x8100 | (bit << 9) | (addr & 255))

    def selector_valid(addr, success, failure):
        load(addr)
        for xor in (1, 3, 1, 4):  # compare1,2,3,7 without changing source
            a.w(0x0A00 | xor)
            a.goto(success, 'Z')
        a.goto(failure)

    def fec_valid(addr, failure):
        load(addr)
        a.w(0x0F14, 0x0828)  # (signed FEC +20) mod256 <=40
        a.goto(failure, 'NC')

    def skip_if_unrequested(mask, destination):
        load(flags)
        a.w(0x0B00 | mask)
        a.goto(destination, 'Z')

    def projection_gate(failure):
        # This is the original UI gate plus the reviewed radio readiness
        # predicate. Re-evaluate it while interrupts are masked immediately
        # before any state is projected. The prior snapshot is not authority
        # over a newer camera-driven native mode change.
        load(0xDD)
        a.w(0x0900)
        a.goto(failure, 'NZ')
        load(0xDC)
        a.w(0x0900)
        a.goto(failure, 'NZ')
        a.w(0x0100)
        a.call(0xAB0C)
        a.w(0x0900)
        a.goto(failure, 'Z')
        a.call(radio_quiet)
        a.w(0x0A01)
        a.goto(failure, 'NZ')
        load(s+0x70)
        a.w(0x0101, 0x1993)  # XORWF native193,W,BANKED
        a.goto(failure, 'NZ')

    a.label('read_inputs')
    for offset in range(0x77, 0x80):
        put(0, s+offset)
    for src, dest in ((0x193, 0x70), (0xC1, 0x71),
                      (0x197, 0x74), (0x198, 0x75), (0x199, 0x76),
                      (0x106, 0x78), (0x107, 0x79)):
        a.movff(src, s+dest)
    for src, dest in ((0xDB, 0x72), (0xF3, 0x73)):
        load(src)
        a.w(0x0B07)
        a.movff(0xFE8, s+dest)
    load(s+0x70)
    a.w(0x0801)
    a.goto('invalid', 'NC')
    selector_valid(s+0x71, 'snapshot_selector_valid', 'invalid')
    a.label('snapshot_selector_valid')
    for offset in (0x74, 0x75, 0x76):
        fec_valid(s+offset, 'invalid')
    for key, bit in SECONDARY_KEYS:
        load(key)
        a.w(0x0B01)
        a.goto('no_secondary_%d' % bit, 'Z')
        setbit(s+0x7A, bit)
        a.label('no_secondary_%d' % bit)
    for key in OTHER_KEYS:
        load(key)
        a.w(0x0B01)
        a.goto('other_key_down', 'NZ')
    a.goto('raw_keys_done')
    a.label('other_key_down')
    put(1, s+0x7B)
    a.label('raw_keys_done')
    put(0x80, s+0x77)
    a.w(0x0100)
    load(0xDD)
    a.w(0x0900)
    a.goto('edit_not_ready', 'NZ')
    load(0xDC)
    a.w(0x0900)
    a.goto('edit_not_ready', 'NZ')
    a.call(0xAB0C)
    a.w(0x0900)
    a.goto('edit_not_ready', 'Z')
    setbit(s+0x77, 0)
    a.label('edit_not_ready')
    a.call(radio_quiet)
    a.w(0x0A01)
    a.goto('radio_not_ready', 'NZ')
    setbit(s+0x77, 1)
    a.label('radio_not_ready')
    if nvm_quiet is not None:
        load(s+0x77)
        a.w(0x0B01)
        a.goto('nvm_not_ready', 'Z')
        load(s+0x7A)
        a.w(0x0900)
        a.goto('nvm_not_ready', 'NZ')
        load(s+0x7B)
        a.w(0x0900)
        a.goto('nvm_not_ready', 'NZ')
        a.call(nvm_quiet)
        a.w(0x0A01)
        a.goto('nvm_not_ready', 'NZ')
        setbit(s+0x77, 2)
        a.label('nvm_not_ready')
    a.w(0x0100, 0x0C01)
    a.label('invalid')
    put(0, s+0x77)
    a.w(0x0100, 0x0C00)

    a.label('apply_native_state')
    a.movff(0xFE8, flags)
    a.w(0x0BF0)
    a.goto('apply_refused', 'NZ')
    skip_if_unrequested(1, 'preflight_fec')
    load(s+1)
    a.w(0x0801)
    a.goto('apply_refused', 'NC')
    a.label('preflight_fec')
    skip_if_unrequested(2, 'preflight_selector')
    for offset in (0x14, 0x15, 0x16):
        fec_valid(s+offset, 'apply_refused')
    a.label('preflight_selector')
    skip_if_unrequested(4, 'preflight_done')
    selector_valid(s+4, 'preflight_done', 'apply_refused')
    a.label('preflight_done')
    projection_gate('apply_refused')
    put(0, accepted)
    a.movff(0xFF2, saved_irq)
    a.label('apply_mask_begin')
    a.w(0x9EF2, 0x9CF2)  # BCF INTCON.GIEH / GIEL, never IPEN
    a.label('apply_masked_recheck')
    projection_gate('apply_restore')
    a.label('apply_projection_begin')
    skip_if_unrequested(1, 'project_fec')
    a.movff(s+1, 0x193)
    a.w(0x0100)
    a.call(0x7B3A)
    a.label('project_fec')
    skip_if_unrequested(2, 'project_selector')
    for i in range(3):
        a.movff(s+0x14+i, 0x197+i)
    a.label('project_selector')
    # A mode-only projection must refresh the original selector's handlers.
    skip_if_unrequested(5, 'project_masks')
    skip_if_unrequested(4, 'refresh_current_selector')
    load(s+4)
    a.goto('call_selector')
    a.label('refresh_current_selector')
    load(0xC1)
    a.label('call_selector')
    a.w(0x0100)
    a.call(0x5CD8)
    a.label('project_masks')
    skip_if_unrequested(8, 'apply_done')
    for src, dest in ((s+5, 0xDB), (s+6, 0xF3)):
        load(src)
        a.w(0x0B07, 0x0100, 0x6F6B)
        load(dest)
        a.w(0x0BF8, 0x116B)
        a.movff(0xFE8, dest)
    a.w(0x0100)
    a.call(0x8816)
    a.label('apply_done')
    put(1, accepted)
    a.label('apply_restore')
    a.w(0x0100 | (saved_irq >> 8))
    a.w(0xBD00 | (saved_irq & 255), 0x8CF2)  # saved GIEL ? BSF live GIEL
    a.w(0xBF00 | (saved_irq & 255))
    a.label('apply_restore_high')
    a.w(0x8EF2)  # saved GIEH ? BSF live GIEH; preserve pending IF bits
    a.label('apply_mask_end')
    load(accepted)
    a.w(0x0100, 0x0012)
    a.label('apply_refused')
    a.w(0x0100, 0x0C00)
    blob = a.finish()
    return {
        'sections': [{'address': base, 'data': blob, 'role': 'sony_native_state_adapter'}],
        'hooks': [], 'exports': a.labels,
        'reserved_ram': [{'start': flags, 'end': flags+1, 'owner': 'sony_apply_request_mask'},
                         {'start': saved_irq, 'end': accepted+1,
                          'owner': 'sony_apply_irq_snapshot_and_result'}],
        'required_imports': ['radio_quiet'] + (['nvm_quiet'] if nvm_quiet is not None else []),
        'unresolved_imports': [],
        'metadata': {'mode': 0x193, 'selector': 0xC1, 'fec': [0x197, 0x198, 0x199],
                     'native_head_model': [0xDB, 0xF3],
                     'snapshot_clock': [0x106, 0x107],
                     'native_gate': 'DD=0, DC=0, original AB0C returns nonzero',
                     'projection_gate': 'native gate + radio_quiet W1 + native193 == snapshot70; fresh masked recheck',
                     'projection_interrupt_policy': 'save and restore GIEH/GIEL individually; preserve pending flags and IPEN',
                     'projection_atomic_scope': 'mode/FEC/selector/native ABC masks and original pure UI helpers',
                     'nv_enabled': nvm_quiet is not None,
                     'native_pure_helpers': [0xAB0C, 0x5CD8, 0x7B3A, 0x8816],
                     'native_nvm': 'unchanged 954E periodic config comparison observes mode193',
                     'radio_or_flash_writes': False},
    }
