#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Address-independent PIC18 AIR2 policy generator; no stock/HSS implementation.

The six native imports are mandatory. Emission is not target qualification:
native hooks, private RAM, interrupts and storage need independent evidence.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

IMPORTS = ('read_inputs', 'apply_native_state', 'redraw', 'tx_frame', 'nv_load', 'nv_commit')
EXPORTS = ('init', 'service', 'power_edit', 'select_row', 'secondary_press',
           'idle_expired', 'display_row')


def required_imports(profile):
    """Resolve optional UI callbacks identically in both linking passes."""
    for field in ('page_hint_on_chord', 'release_redraw'):
        if field in profile and type(profile[field]) is not bool:
            raise ValueError(field + ' must be boolean')
    return IMPORTS + (('page_hint',) if profile.get('page_hint_on_chord', False) else ())


class Asm:
    """Small classic PIC18 assembler, byte addresses and fixed-size branches."""
    def __init__(self, base):
        self.base = base
        self.data = bytearray()
        self.labels = {}
        self.fixups = []
        self.notes = []

    @property
    def pc(self): return self.base + len(self.data)
    @property
    def code(self): return self.data
    def w(self, word): self.data += int(word & 0xFFFF).to_bytes(2, 'little')
    def emit(self, *words):
        for word in words: self.w(word)
    def label(self, name):
        if name in self.labels: raise ValueError('duplicate label: ' + name)
        self.labels[name] = self.pc
    def movff(self, source, destination):
        if not 0 <= source < 0x1000 or not 0 <= destination < 0x1000:
            raise ValueError('MOVFF outside register address space')
        self.emit(0xC000 | source, 0xF000 | destination)
    def _absolute(self, opcode, target):
        if isinstance(target, str):
            self.fixups.append((len(self.data), opcode, target))
            target = 0
        if target & 1: raise ValueError('odd code address')
        self.emit(opcode | ((target >> 1) & 255), 0xF000 | ((target >> 9) & 0xFFF))
    def call(self, target): self._absolute(0xEC00, target)
    def goto(self, target): self._absolute(0xEF00, target)
    def jump(self, target, cond=None):
        if cond is not None:
            inverse = {'BZ': 0xE100, 'BNZ': 0xE000, 'BC': 0xE300,
                       'BNC': 0xE200, 'BN': 0xE700, 'BNN': 0xE600}
            self.w(inverse[cond] | 2)  # Skip the following 2-word GOTO.
        self.goto(target)
    def finalize(self):
        result = bytearray(self.data)
        for offset, opcode, name in self.fixups:
            if name not in self.labels: raise ValueError('unresolved label: ' + name)
            addr = self.labels[name]
            result[offset:offset+4] = ((opcode | ((addr >> 1) & 255)).to_bytes(2, 'little')
                                      + (0xF000 | ((addr >> 9) & 0xFFF)).to_bytes(2, 'little'))
        return bytes(result)


class Codegen:
    def __init__(self, base, profile, backend):
        self.a = Asm(base)
        self.profile = profile
        self.base = profile['state_base']
        self.imports = backend.get('exports', backend)
    def label(self, name): self.a.label(name)
    def literal(self, value): self.a.w(0x0E00 | (value & 255))
    def get(self, offset):
        self.a.movff(self.base + offset, 0xFE8)
        self.a.w(0x0900)  # IORLW 0, update N/Z without modifying C.
    def put(self, offset): self.a.movff(0xFE8, self.base + offset)
    def copy(self, source, dest): self.a.movff(self.base + source, self.base + dest)
    def set(self, offset, value): self.literal(value); self.put(offset)
    def clear(self, offset): self.set(offset, 0)
    def call(self, name): self.a.call(name)
    def go(self, name, cond=None): self.a.jump(name, cond)
    def backend(self, name): self.a.call(self.imports[name])
    def ret(self, value=None):
        self.a.w(0x0012 if value is None else 0x0C00 | (value & 255))
    def xor_literal(self, value): self.a.w(0x0A00 | (value & 255))
    def and_literal(self, value): self.a.w(0x0B00 | (value & 255))
    def alu(self, op, offset):
        address = self.base + offset
        bases = {'ADDWF': 0x2400, 'ADDWFC': 0x2000, 'SUBWF': 0x5C00,
                 'SUBWFB': 0x5800, 'XORWF': 0x1800, 'ANDWF': 0x1400,
                 'IORWF': 0x1000}
        self.a.w(0x0100 | (address >> 8))
        self.a.w(bases[op] | 0x100 | (address & 255))
    def inc(self, offset):
        address = self.base + offset
        self.a.w(0x0100 | (address >> 8))
        self.a.w(0x2B00 | (address & 255))
    def equal(self, offset, value, label):
        self.get(offset); self.xor_literal(value); self.go(label, 'BZ')
    def bit(self, offset, mask, label, present=True):
        self.get(offset); self.and_literal(mask); self.go(label, 'BNZ' if present else 'BZ')


def _emit_base(c):
    c.label('check_ready_edit')
    c.get(0); c.xor_literal(0xA8); c.go('return_zero', 'BNZ')
    c.bit(0x17, 2, 'return_zero')
    c.get(0x77); c.and_literal(0x81); c.xor_literal(0x81); c.go('return_zero', 'BNZ')
    c.get(0x28); c.go('return_zero', 'BNZ'); c.ret(1)
    c.label('return_zero'); c.ret(0)
    c.label('return_one'); c.ret(1)

    c.label('snapshot')
    for i in range(0x18): c.copy(i, 0x40 + i)
    c.ret()
    c.label('rollback')
    for i in range(0x18): c.copy(0x40 + i, i)
    c.ret(0)
    c.label('commit_ui')
    c.backend('apply_native_state'); c.xor_literal(0)
    c.go('rollback', 'BZ')
    c.get(0x17); c.a.w(0x0901); c.put(0x17); c.backend('redraw'); c.ret(1)

    c.label('clear_relative')
    for i in range(0x0E, 0x14): c.clear(i)
    c.clear(7); c.ret()

    c.label('boot_projection')
    c.get(0); c.xor_literal(0xA8); c.go('return_zero', 'BNZ')
    c.bit(0x17, 2, 'return_one', False)
    c.bit(0x77, 0x80, 'return_zero', False)
    c.get(0x70); c.alu('XORWF', 0x2D); c.go('boot_native_changed', 'BNZ')
    c.literal(9); c.go('boot_apply_projection')
    c.label('boot_native_changed')
    # A native/camera mode change supersedes only the saved mode. Keep the
    # saved switches pending until a fresh-gated masks-only projection works;
    # otherwise sync_context would import native ABC defaults and persist them.
    c.copy(0x70, 1)
    # Modes are 0/1. Sentinel 2 latches the native-mode winner across retries,
    # including a later native transition back to the initial boot mode.
    c.set(0x2D, 2)
    c.get(0x17); c.a.w(0x0901); c.put(0x17)
    c.literal(8)
    c.label('boot_apply_projection')
    c.backend('apply_native_state'); c.xor_literal(0)
    c.go('return_zero', 'BZ')
    c.get(0x17); c.and_literal(0xFD); c.put(0x17)
    # Projection changed the native mode; refresh the snapshot before sync.
    c.backend('read_inputs'); c.backend('redraw'); c.ret(1)

    c.label('sync_context')
    c.clear(0x6F)
    # Snapshot mode is authoritative. Never continue an old-domain TX tail.
    c.get(0x77); c.and_literal(0x80); c.go('return_zero', 'BZ')
    c.get(0x70); c.alu('XORWF', 1); c.go('sync_same_mode', 'BZ')
    c.copy(0x70, 1); c.clear(0x28)
    c.get(0x17); c.a.w(0x0901); c.put(0x17); c.set(0x6F, 1)
    c.get(0x18); c.go('sync_no_gesture', 'BZ'); c.set(0x18, 2)
    c.label('sync_no_gesture')
    c.get(1); c.go('sync_same_mode', 'BZ')
    c.equal(2, 1, 'sync_clear_relative'); c.go('sync_same_mode')
    c.label('sync_clear_relative'); c.call('clear_relative')
    c.label('sync_same_mode')
    c.copy(0x71, 4)
    for i in range(3): c.copy(0x74+i, 0x14+i)
    # Keep the hidden DEF intent; camera/native side owns current ABC flags.
    for dst, src in ((5, 0x72), (6, 0x73)):
        c.get(dst); c.and_literal(0x38); c.put(0x6E)
        c.get(src); c.and_literal(7); c.alu('IORWF', 0x6E); c.put(dst)
    c.get(0x6F); c.go('sync_done', 'BZ'); c.backend('redraw')
    c.label('sync_done')
    c.ret(1)

    c.label('init')
    # Exact core-owned prefix only. Provider context is live at startup.
    c.a.emit(0xEE00 | (c.base >> 8), 0xF000 | (c.base & 255))  # LFSR 0,base
    c.literal(0xB0)
    c.label('init_clear_loop')
    c.a.w(0x6AEE)  # CLRF POSTINC0, ACCESS
    c.a.w(0x0FFF)  # ADDLW -1
    c.go('init_clear_loop', 'BNZ')
    c.backend('read_inputs')
    c.get(0x77); c.and_literal(0x80); c.go('return_zero', 'BZ')
    c.get(0x70); c.a.w(0x0801); c.go('return_zero', 'BNC')
    c.copy(0x70, 1); c.set(2, 1); c.copy(0x71, 4)
    c.get(0x72); c.and_literal(7); c.put(5)
    c.get(0x73); c.and_literal(7); c.put(6)
    for i in range(6): c.set(8+i, 50)
    for i in range(3): c.copy(0x74+i, 0x14+i)
    c.set(0, 0xA8)
    if c.profile.get('nv_enabled', False):
        c.backend('nv_load'); c.xor_literal(0); c.go('init_done', 'BZ')
        # A cold native permission gate may not yet be ready. Keep the saved
        # intent pending without transmitting or saving over it. A subsequent
        # external native-mode change wins instead of being forced back.
        c.call('record_restore'); c.xor_literal(0); c.go('init_done', 'BZ')
        c.copy(0x70, 0x2D); c.set(0x17, 2); c.call('boot_projection')
    c.label('init_done'); c.backend('redraw'); c.ret(1)

    c.label('edit_entry')
    c.backend('read_inputs'); c.call('boot_projection'); c.xor_literal(0)
    c.go('return_zero', 'BZ'); c.call('sync_context')
    c.call('check_ready_edit'); c.xor_literal(0); c.go('return_zero', 'BZ')
    c.get(0x18); c.go('edit_entry_ok', 'BZ')
    c.set(0x18, 2); c.ret(0)
    c.label('edit_entry_ok'); c.ret(1)

    c.label('select_row')
    c.put(0x60); c.call('edit_entry'); c.xor_literal(0); c.go('return_zero', 'BZ')
    c.get(0x60)
    c.label('select_row_internal')
    c.put(0x60)
    for row in (1, 2, 3): c.equal(0x60, row, 'select_valid')
    c.ret(0)
    c.label('select_valid'); c.call('snapshot')
    c.get(0x60); c.alu('XORWF', 4); c.go('select_other', 'BNZ')
    c.set(4, 7); c.go('select_applied')
    c.label('select_other'); c.copy(0x60, 4)
    c.label('select_applied')
    c.equal(2, 2, 'select_commit')
    c.get(1); c.go('select_clear_relative', 'BNZ')
    c.get(3); c.go('select_commit', 'BZ')  # TTL ABC remains FEC.
    c.label('select_clear_relative'); c.call('clear_relative')
    c.label('select_commit'); c.literal(4); c.go('commit_ui')

    c.label('toggle_page'); c.call('snapshot')
    c.get(3); c.xor_literal(1); c.put(3)
    c.literal(0)
    if c.profile.get('page_hint_on_chord', False):
        c.call('commit_ui'); c.xor_literal(0)
        c.go('return_zero', 'BZ')
        c.backend('page_hint'); c.ret(1)
    else:
        c.go('commit_ui')
    c.label('toggle_manual')
    c.get(1); c.go('return_zero', 'BZ')
    c.call('snapshot'); c.get(2); c.xor_literal(3); c.put(2)
    c.equal(2, 2, 'manual_commit'); c.call('clear_relative')
    c.label('manual_commit'); c.literal(0); c.go('commit_ui')

    c.label('idle_expired')
    c.get(0); c.xor_literal(0xA8); c.go('return_zero', 'BNZ')
    c.equal(2, 2, 'return_zero')
    # Expiry may occur while camera/native transport owns the foreground.
    # Use the same freshly sampled gate as an edit, rather than stale flags.
    # Native wrappers retain their expired deadline when this returns zero.
    c.backend('read_inputs'); c.call('check_ready_edit'); c.xor_literal(0)
    c.go('return_zero', 'BZ')
    # A mount may allow a local edit while its native sender is occupied.
    # Idle cleanup can wait; require the independent radio-ready gate too.
    c.bit(0x77, 2, 'return_zero', False)
    c.call('clear_relative'); c.backend('redraw'); c.ret(1)


def _emit_power(c):
    # Per-group getter supplies value and linearized bounds. Bias conversion
    # makes signed FEC/relative ranges comparable with unsigned PIC18 carry.
    for g in range(6):
        c.label('get_g%d' % g)
        if g < 3:
            c.get(1); c.go('get_g%d_fec' % g, 'BZ')
        c.equal(2, 2, 'get_g%d_abs' % g)
        c.set(0x65, 99); c.set(0x66, 198); c.get(0x0E+g); c.ret()
        c.label('get_g%d_abs' % g)
        c.set(0x65, 255); c.set(0x66, 99); c.get(8+g); c.ret()
        if g < 3:
            c.label('get_g%d_fec' % g)
            c.set(0x65, 20); c.set(0x66, 40); c.get(0x14+g); c.ret()
        c.label('put_g%d' % g); c.put(0x67)
        if g < 3:
            c.get(1); c.go('put_g%d_fec' % g, 'BZ')
        c.equal(2, 2, 'put_g%d_abs' % g)
        c.copy(0x67, 0x0E+g)
        c.get(7); c.a.w(0x0900 | (1 << g)); c.put(7); c.ret()
        c.label('put_g%d_abs' % g); c.copy(0x67, 8+g); c.ret()
        if g < 3:
            c.label('put_g%d_fec' % g); c.copy(0x67, 0x14+g); c.ret()

    c.label('make_selection')
    c.clear(0x68)
    c.equal(4, 7, 'selection_all')
    for page in range(2):
        c.equal(3, page, 'selection_page%d' % page)
    c.ret(0)
    for page in range(2):
        c.label('selection_page%d' % page)
        for row in range(1, 4):
            c.equal(4, row, 'selection_g%d' % (page*3+row-1))
        c.ret(0)
    for g in range(6):
        c.label('selection_g%d' % g); c.set(0x68, 1 << g); c.ret(1)
    c.label('selection_all'); c.set(0x68, 0x3F); c.ret(1)

    c.label('power_edit'); c.put(0x60)
    c.call('edit_entry'); c.xor_literal(0); c.go('return_zero', 'BZ')
    for value in (1, 10, 255, 246): c.equal(0x60, value, 'power_step_valid')
    c.ret(0)
    c.label('power_step_valid')
    c.call('make_selection'); c.get(5); c.alu('ANDWF', 0x68); c.put(0x68)
    c.go('return_zero', 'BZ')
    for g in range(6):
        c.bit(0x68, 1 << g, 'preflight_next%d' % g, False)
        c.call('get_g%d' % g); c.alu('ADDWF', 0x65); c.put(0x67)
        c.bit(0x60, 0x80, 'preflight_negative%d' % g)
        c.get(0x60); c.alu('ADDWF', 0x67); c.put(0x67)
        c.get(0x67); c.alu('SUBWF', 0x66); c.go('return_zero', 'BNC')
        c.go('preflight_next%d' % g)
        c.label('preflight_negative%d' % g)
        c.get(0x60); c.a.w(0x0800); c.put(0x69)
        c.get(0x69); c.alu('SUBWF', 0x67); c.go('return_zero', 'BNC')
        c.label('preflight_next%d' % g)
    c.call('snapshot')
    for g in range(6):
        c.bit(0x68, 1 << g, 'power_apply_next%d' % g, False)
        c.call('get_g%d' % g); c.alu('ADDWF', 0x60); c.call('put_g%d' % g)
        c.label('power_apply_next%d' % g)
    # Preserve transaction arguments across arbitrary native redraw scratch.
    c.copy(0x68, 0x2A); c.copy(0x60, 0x2B)
    c.literal(2); c.call('commit_ui'); c.xor_literal(0)
    c.go('return_zero', 'BZ')
    c.set(0x28, 1); c.set(0x29, 1); c.clear(0x2C); c.copy(1, 0x2D); c.ret(1)

    for name, kind, maskoffset in (('switch_head', 2, 5), ('switch_model', 3, 6)):
        c.label(name); c.call('make_selection'); c.call('snapshot')
        # Toggle all selected to ON unless all are already ON.
        c.get(maskoffset); c.alu('ANDWF', 0x68); c.alu('XORWF', 0x68)
        c.go(name+'_off', 'BZ')
        c.get(maskoffset); c.alu('IORWF', 0x68); c.put(maskoffset); c.go(name+'_apply')
        c.label(name+'_off'); c.get(0x68); c.xor_literal(255)
        c.alu('ANDWF', maskoffset); c.put(maskoffset)
        c.label(name+'_apply'); c.copy(0x68, 0x2A)
        c.literal(8); c.call('commit_ui'); c.xor_literal(0); c.go('return_zero', 'BZ')
        c.set(0x28, kind); c.set(0x29, 1); c.clear(0x2C); c.copy(1, 0x2D); c.ret(1)


def _emit_display(c):
    c.label('display_row'); c.put(0x61)
    for page in range(2): c.equal(3, page, 'display_page%d' % page)
    c.ret(0)
    for page in range(2):
        c.label('display_page%d' % page)
        for row in range(1, 4): c.equal(0x61, row, 'display_g%d' % (page*3+row-1))
        c.ret(0)
    for g in range(6):
        c.label('display_g%d' % g)
        c.bit(5, 1 << g, 'display_off', False)
        if g < 3:
            c.get(1); c.go('display_fec%d' % g, 'BZ')
        c.equal(2, 2, 'display_abs%d' % g)
        c.bit(7, 1 << g, 'display_blank', False)
        c.copy(0x0E+g, 0x61); c.ret(1)
        c.label('display_abs%d' % g); c.copy(8+g, 0x61); c.ret(2)
        if g < 3:
            c.label('display_fec%d' % g); c.copy(0x14+g, 0x61); c.ret(1)
    c.label('display_off'); c.clear(0x61); c.ret(3)
    c.label('display_blank'); c.clear(0x61); c.ret(0)


def _emit_tx(c):
    c.label('frame_clear')
    for i in range(16): c.clear(0x30+i)
    for i in range(1, 4): c.set(0x30+i, 255)
    c.set(0x34, 1); c.ret()
    c.label('frame_snapshot'); c.call('frame_clear')
    c.set(0x30, 0x27); c.set(0x35, 0x11)
    for g in range(6): c.copy(8+g, 0x36+g)
    c.copy(5, 0x3C); c.copy(6, 0x3D); c.ret()
    c.label('frame_fec'); c.call('frame_clear')
    c.set(0x30, 0x27); c.set(0x35, 0x25)
    for g in range(3): c.copy(0x14+g, 0x36+g)
    c.ret()
    c.label('frame_group'); c.call('frame_clear')
    c.copy(0x29, 0x30); c.copy(0x29, 0x36); c.ret()
    c.label('tx_attempt')
    c.get(0x28); c.go('return_zero', 'BZ')
    c.bit(0x77, 2, 'return_zero', False)
    c.equal(0x28, 1, 'tx_power')
    c.go('tx_group')
    c.label('tx_power')
    c.get(0x2C); c.go('tx_power_manual', 'BNZ')
    c.get(1); c.go('tx_power_skip_fec', 'BNZ')
    c.bit(0x2A, 7, 'tx_power_skip_fec', False)
    c.call('frame_fec'); c.backend('tx_frame'); c.xor_literal(0); c.go('return_zero', 'BZ')
    c.set(0x2C, 1); c.ret(1)
    c.label('tx_power_skip_fec'); c.set(0x2C, 1)
    c.label('tx_power_manual')
    c.get(1); c.go('tx_power_manual_mask', 'BNZ')
    c.get(0x2A); c.and_literal(0x38); c.put(0x2A)
    c.label('tx_power_manual_mask')
    c.get(0x2A); c.go('tx_finish', 'BZ')
    c.equal(2, 2, 'tx_snapshot')
    c.go('tx_group')
    c.label('tx_snapshot'); c.call('frame_snapshot')
    c.backend('tx_frame'); c.xor_literal(0); c.go('return_zero', 'BZ')
    c.clear(0x28); c.ret(1)
    c.label('tx_group')
    for g in range(6): c.equal(0x29, g+1, 'tx_group%d' % g)
    c.go('tx_finish')
    for g in range(6):
        c.label('tx_group%d' % g)
        c.bit(0x2A, 1 << g, 'tx_skip_group%d' % g, False)
        c.call('frame_group')
        c.equal(0x28, 1, 'tx_relative%d' % g)
        c.equal(0x28, 3, 'tx_model%d' % g)
        c.get(0x2C); c.go('tx_model%d' % g, 'BNZ')
        c.set(0x35, 1); c.bit(5, 1 << g, 'tx_send_head_on%d' % g)
        c.go('tx_send_last%d' % g)
        c.label('tx_send_head_on%d' % g); c.clear(0x35)
        c.backend('tx_frame'); c.xor_literal(0); c.go('return_zero', 'BZ')
        c.set(0x2C, 1); c.ret(1)
        c.label('tx_model%d' % g)
        c.set(0x35, 3); c.bit(6, 1 << g, 'tx_model_on%d' % g)
        c.go('tx_send_last%d' % g)
        c.label('tx_model_on%d' % g); c.set(0x35, 2); c.go('tx_send_last%d' % g)
        c.label('tx_relative%d' % g)
        for step, cmd in ((1,6), (255,7), (10,13), (246,14)):
            c.equal(0x2B, step, 'tx_relative%d_cmd%d' % (g,cmd))
        c.go('tx_finish')
        for cmd in (6,7,13,14):
            c.label('tx_relative%d_cmd%d' % (g,cmd)); c.set(0x35, cmd); c.go('tx_send_last%d' % g)
        c.label('tx_send_last%d' % g)
        c.backend('tx_frame'); c.xor_literal(0); c.go('return_zero', 'BZ')
        c.inc(0x29)
        c.equal(0x28, 1, 'return_one')
        c.clear(0x2C); c.ret(1)
        c.label('tx_skip_group%d' % g); c.inc(0x29); c.go('tx_group')
    c.label('tx_finish'); c.clear(0x28); c.ret(0)

    c.label('service')
    c.backend('read_inputs'); c.call('boot_projection'); c.xor_literal(0)
    c.go('return_zero', 'BZ'); c.call('sync_context')
    c.get(0); c.xor_literal(0xA8); c.go('return_zero', 'BNZ')
    c.call('gesture_poll')
    c.call('tx_attempt'); c.xor_literal(0)
    c.go('return_one', 'BNZ')  # Fresh enqueue: never use a stale NV-ready bit.
    if c.profile.get('nv_enabled', False):
        c.get(0x28); c.go('return_zero', 'BNZ')
        c.get(0x18); c.go('return_zero', 'BNZ')
        c.bit(0x17, 0x80, 'return_zero')
        c.bit(0x17, 1, 'return_zero', False)
        c.backend('read_inputs')
        c.get(0x77); c.and_literal(0x84); c.xor_literal(0x84); c.go('return_zero', 'BNZ')
        c.call('sync_context')
        c.get(0x18); c.go('return_zero', 'BNZ')
        # 2E:F means last durable sequence. Retries must not consume it, and
        # the first save after reboot must not repeat the loaded sequence.
        c.copy(0x2E, 0x6C); c.copy(0x2F, 0x6D)
        c.inc(0x2E); c.get(0x2E); c.go('nv_sequence_ready', 'BNZ'); c.inc(0x2F)
        c.label('nv_sequence_ready')
        c.call('record_capture'); c.xor_literal(0); c.go('nv_retry', 'BZ')
        c.backend('nv_commit'); c.put(0x69)
        c.equal(0x69, 0, 'nv_retry')
        c.equal(0x69, 1, 'nv_committed')
        c.get(0x17); c.a.w(0x0980); c.put(0x17); c.go('nv_retry')
        c.label('nv_committed')
        c.copy(0x44, 0x2E); c.copy(0x45, 0x2F)
        c.clear(0x17); c.ret(1)
        c.label('nv_retry')
        c.copy(0x6C, 0x2E); c.copy(0x6D, 0x2F); c.ret(0)
    c.ret(0)


def construct(original=None, *, app_base=0x4000, code_base, profile, backend):
    """Emit policy with explicit mappings; unresolved native imports always fail."""
    if type(code_base) is not int or code_base & 1 or code_base < app_base:
        raise ValueError('even explicit MCU code_base required')
    profile = dict(profile)
    for name in ('model_tag','state_base','state_span','window_counts','stable_counts','clock_mask','code_limit'):
        if name not in profile: raise ValueError('missing profile field: '+name)
    if profile['model_tag'] not in ('F','N','O','S'): raise ValueError('unknown mount')
    if type(profile['code_limit']) is not int or profile['code_limit'] & 1 or profile['code_limit'] <= code_base:
        raise ValueError('even code_limit above code_base required')
    if profile['state_span'] != 0x180: raise ValueError('ABI requires exact 0x180 state span')
    if not 0 <= profile['state_base'] <= 0xF00-0x180: raise ValueError('private state reaches SFR')
    imports = backend.get('exports', backend)
    imports_required = required_imports(profile)
    for name in imports_required:
        if not isinstance(imports.get(name), int) or imports[name] <= 0 or imports[name] & 1:
            raise ValueError('missing/alignment-invalid import: '+name)
    c = Codegen(code_base, profile, backend)
    _emit_base(c); _emit_power(c); _emit_display(c); _emit_tx(c)
    from gesture_runtime_codegen import emit_gestures
    gesture = emit_gestures(c)
    if profile.get('nv_enabled', False):
        from record_runtime_codegen import emit_record
        emit_record(c)
    data = c.a.finalize()
    if code_base < app_base or code_base + len(data) > profile['code_limit']:
        raise ValueError('emitted core exceeds proved code allocation')
    if original is not None:
        offset = code_base-app_base
        if offset < 0 or offset+len(data) > len(original): raise ValueError('code outside input extent')
        if original[offset:offset+len(data)] != b'\xff'*len(data): raise ValueError('core cave is not erased')
    proofs = ('ram_proven','hardware_proven','clock_proven','native_interfaces_proven')
    qualified = all(profile.get(name) is True for name in proofs)
    return {'sections':[{'address':code_base,'data':data,'role':'air2_core'}], 'hooks':[],
            'exports':{name:c.a.labels[name] for name in EXPORTS},
            'labels':dict(c.a.labels), 'required_imports':list(imports_required), 'unresolved_imports':[],
            'reserved_ram':[{'start':profile['state_base'],'end':profile['state_base']+0x180,'owner':'AIR2 core/provider'}],
            'metadata':{'abi_version':1,'code_sha256':hashlib.sha256(data).hexdigest(),
                        'model_tag':profile['model_tag'],'target_qualified':qualified,
                        'nv_enabled':bool(profile.get('nv_enabled',False)), 'gesture':gesture,
                        'hss_policy_linked':False, 'state_initial_clear_span':0xB0,
                        'unqualified_emission_is_not_a_flashable_build':not qualified}}
