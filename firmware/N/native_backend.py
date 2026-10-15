#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Nikon C5 native AIR2 backend, offline adapter construction only.

This is not a ready-to-flash image: RAM, hardware and hook proof are separate
build gates. The unmodified Nikon LCD formatter and TX queue are called in their
own ABI. No Canon HSS routine or address is imported. NVM stays disabled until
the new journal's erase/program geometry has been established independently.
"""
from __future__ import annotations

import hashlib

STOCK_SHA256 = 'd8a58e3bbaeee752b31e698c287c474b4ab027fb29939720e1441a39cb3f0aba'
MANDATORY = ('read_inputs', 'apply_native_state', 'redraw', 'tx_frame', 'nv_load', 'nv_commit')


def words(*values):
    return b''.join(int(x).to_bytes(2, 'little') for x in values)


def absolute(op, address):
    if address & 1:
        raise ValueError('odd instruction target')
    return words(op | ((address // 2) & 255), 0xF000 | (address // 2 >> 8))


class Asm:
    """Small model-local encoder, not linked to a previous HSS patch."""
    def __init__(self, base):
        self.base, self.data, self.labels, self.fixups = base, bytearray(), {}, []

    @property
    def pc(self):
        return self.base + len(self.data)

    def w(self, value, note=''):
        self.data.extend(words(value))

    def emit(self, raw, note=''):
        self.data.extend(raw)

    def label(self, name):
        if name in self.labels:
            raise ValueError('duplicate label: ' + name)
        self.labels[name] = self.pc

    def call(self, address):
        self.emit(absolute(0xEC00, address))

    def goto(self, address):
        self.emit(absolute(0xEF00, address))

    def movff(self, src, dst):
        self.emit(words(0xC000 | src, 0xF000 | dst))

    def jump(self, name, kind='BRA'):
        self.fixups.append((len(self.data), self.pc, name, kind))
        self.emit(words(0) if kind == 'BRA' else words(0, 0, 0))

    def lit(self, value):
        self.w(0x0E00 | (value & 255))

    def load(self, address):
        self.movff(address, 0xFE8)

    def store(self, address):
        self.movff(0xFE8, address)

    def put(self, address, value):
        self.lit(value)
        self.store(address)

    def ret(self, value=None):
        self.w(0x0012 if value is None else 0x0C00 | (value & 255))

    def bit(self, address, bit, op):
        # All native/extension addresses are explicitly bank selected; IRQ
        # hardware saves/restores BSR, and the outer wrapper restores its caller.
        self.w(0x0100 | (address >> 8))
        self.w({'set': 0x8100, 'clear': 0x9100,
                'skip_set': 0xA100, 'skip_clear': 0xB100}[op] | (bit << 9) | (address & 255))

    def finalize(self):
        inverse = {'BZ': 0xE100, 'BNZ': 0xE000, 'BC': 0xE300, 'BNC': 0xE200}
        for off, pc, label, kind in self.fixups:
            delta = (self.labels[label] - pc - 2) // 2
            if kind == 'BRA':
                if not -1024 <= delta <= 1023:
                    raise ValueError('BRA out of range')
                value = 0xD000 | (delta & 2047)
            else:
                self.data[off:off + 6] = words(inverse[kind] | 2) + absolute(0xEF00, self.labels[label])
                continue
            self.data[off:off + 2] = words(value)
        return bytes(self.data)


def construct(original, *, app_base=0x4000, code_base=0xB000,
              state_base=0x680, imports=None, profile=None):
    """Emit six backend exports, with no original-code hooks or side effects.

    ``imports['display_row']`` must resolve to the shared core. A missing import
    produces an explicit unresolved status, never a deployable artifact.
    """
    if app_base != 0x4000 or hashlib.sha256(original).hexdigest() != STOCK_SHA256:
        raise ValueError('not the independently decoded Nikon C5 stock image')
    if code_base < 0xAA80 or state_base < 0x600 or state_base + 0x180 > 0x800:
        raise ValueError('outside candidate allocation; update proof before expanding')
    imports = dict(imports or {})
    profile = dict(profile or {})
    hint_counts = int(profile.get('page_hint_counts', 650))
    nv_ready_enabled = bool(profile.get('nv_enabled') and profile.get('native_nv_gate_proven'))
    if not 1 <= hint_counts <= 0x7FFF:
        raise ValueError('page hint must be bounded native tick counts')
    display = imports.get('display_row', 0)
    s = lambda offset: state_base + offset
    a = Asm(code_base)

    a.label('read_inputs')
    # Zero the complete input extension before validating the model pointer.
    for n in range(0x70, 0x80):
        a.put(s(n), 0)
    for addr, val in ((0x49, 0xB1), (0x4A, 1)):
        a.load(addr); a.w(0x0A00 | val); a.jump('invalid_inputs', 'BNZ')
    a.load(0x1B1); a.w(0x0B01); a.store(s(0x70))
    a.load(0x1B1); a.w(0x0BFE); a.jump('invalid_inputs', 'BNZ')
    a.movff(0x60, s(0x71))
    for good in (1, 2, 3, 7):
        a.load(0x60); a.w(0x0A00 | good); a.jump('selector_valid', 'BZ')
    a.jump('invalid_inputs')
    a.label('selector_valid')
    for src, dst in ((0x4C, 0x72), (0x50, 0x73)):
        a.load(src); a.w(0x0B07); a.store(s(dst))
    for i in range(3):
        a.movff(0x1B5 + i, s(0x74 + i))
    a.movff(0x11B, s(0x78)); a.movff(0x11C, s(0x79))
    for src, bit in ((0x282, 0), (0x286, 1), (0x28A, 2)):
        a.bit(src, 0, 'skip_set'); a.jump(f'raw_skip_{bit}')
        a.bit(s(0x7A), bit, 'set'); a.label(f'raw_skip_{bit}')
    for index in (0, 1, 2, 3, 7, 8, 9, 10):
        a.bit(0x272 + 4 * index, 0, 'skip_set'); a.jump(f'other_skip_{index}')
        a.bit(s(0x7B), 0, 'set'); a.label(f'other_skip_{index}')
    a.put(s(0x77), 0x80)
    a.load(0x4D); a.w(0x0900); a.jump('valid_inputs', 'BNZ')
    a.w(0x0100); a.call(0xA6C6); a.w(0x0900); a.jump('valid_inputs', 'BZ')
    a.load(0x4B); a.w(0x0900); a.jump('valid_inputs', 'BNZ')
    for pending in (0x85, 0x1B8):
        a.load(pending); a.w(0x0900); a.jump('valid_inputs', 'BNZ')
    a.bit(s(0x77), 0, 'set')
    a.load(0x2BA); a.w(0x0900); a.jump('valid_inputs', 'BNZ')
    a.load(0x95); a.w(0x0900); a.jump('valid_inputs', 'BNZ')
    a.bit(s(0x77), 1, 'set')
    if nv_ready_enabled:
        # The shared journal calls this again inside its short write critical
        # section. Read actual pending flags; never re-enable interrupts here.
        for busy in (s(0x7A),s(0x7B),s(0x18),s(0x28),0x1CC):
            a.load(busy); a.w(0x0900); a.jump('valid_inputs','BNZ')
        a.load(0x53); a.w(0x0B02); a.jump('valid_inputs','BNZ')
        a.load(0xFF0); a.w(0x0B03); a.jump('valid_inputs','BNZ')
        a.load(0xF9E); a.w(0x0B20); a.jump('valid_inputs','BNZ')
        a.load(0xFAD); a.w(0x0B02); a.jump('valid_inputs','BZ')
        a.bit(s(0x77),2,'set')
    a.label('valid_inputs'); a.ret(1)
    a.label('invalid_inputs'); a.put(s(0x77), 0); a.ret(0)

    a.label('apply_native_state')
    a.store(s(0xB0))
    # Refresh native gates and validate every requested field before any write.
    # Radio busy does not by itself block a local edit; enqueue has a separate
    # fresh check. Camera/exclusive/native-input state does block projection.
    a.call(a.labels['read_inputs']); a.w(0x0900); a.jump('apply_refused', 'BZ')
    a.load(s(0x77)); a.w(0x0B81); a.w(0x0A81); a.jump('apply_refused', 'BNZ')
    a.load(s(0xB0)); a.w(0x0BF0); a.jump('apply_refused', 'BNZ')
    a.bit(s(0xB0), 0, 'skip_set'); a.jump('validate_mode_done')
    a.load(s(1)); a.w(0x0BFE); a.jump('apply_refused', 'BNZ')
    a.label('validate_mode_done')
    a.bit(s(0xB0), 1, 'skip_set'); a.jump('validate_fec_done')
    for i in range(3):
        # Signed -20..20 mapped to unsigned 0..40 without overflow.
        a.load(s(0x14+i)); a.w(0x0F14); a.w(0x0828); a.jump('apply_refused', 'BNC')
    a.label('validate_fec_done')
    a.bit(s(0xB0), 2, 'skip_set'); a.jump('validate_selector_done')
    for row in (1, 2, 3, 7):
        a.load(s(4)); a.w(0x0A00 | row); a.jump('validate_selector_done', 'BZ')
    a.jump('apply_refused')
    a.label('validate_selector_done')
    a.bit(s(0xB0), 3, 'skip_set'); a.jump('validate_masks_done')
    for coreoff in (5, 6):
        a.load(s(coreoff)); a.w(0x0BC0); a.jump('apply_refused', 'BNZ')
    a.label('validate_masks_done')
    # Match the proved no-RF subset of 7B88. Never call its 75AA/94CA tail:
    # those contain radio side effects and would duplicate core transactions.
    a.bit(s(0xB0), 0, 'skip_set'); a.jump('apply_mode_ok')
    a.load(s(1)); a.w(0x0BFE); a.jump('apply_refused', 'BNZ')
    a.load(s(1)); a.w(0x0101); a.w(0x19B1); a.jump('apply_mode_ok', 'BZ')
    a.movff(s(1), 0x1B1); a.put(0x61, 0)
    a.lit(0); a.w(0x0100); a.call(0xA83C)
    a.put(0x20, 0); a.put(0x21, 0); a.call(0x9EEC); a.call(0x56D4)
    a.load(0x60); a.w(0x0100); a.call(0x5986); a.call(0x7756)
    a.label('apply_mode_ok')
    a.bit(s(0xB0), 1, 'skip_set'); a.jump('apply_fec_done')
    for i in range(3):
        a.movff(s(0x14 + i), 0x1B5 + i)
    a.label('apply_fec_done')
    a.bit(s(0xB0), 2, 'skip_set'); a.jump('apply_selector_done')
    a.load(s(4)); a.w(0x0100); a.call(0x5986)
    a.label('apply_selector_done')
    a.bit(s(0xB0), 3, 'skip_set'); a.jump('apply_masks_done')
    # Keep ABC semantics even when the user is looking at DEF.
    for coreoff, native in ((5, 0x4C), (6, 0x50)):
        a.load(native); a.w(0x0BF8); a.store(s(0xB1))
        a.load(s(coreoff)); a.w(0x0B07)
        a.w(0x0100 | (s(0xB1) >> 8)); a.w(0x1100 | (s(0xB1) & 255)); a.store(native)
    a.label('apply_masks_done'); a.ret(1)
    a.label('apply_refused'); a.ret(0)

    a.label('redraw')
    for row, numeric in ((1, 0x89), (2, 0x8B), (3, 0x8D)):
        a.lit(row); a.call(display); a.store(s(0xB1))
        a.put(0x11, 0x88); a.put(0x12, numeric)
        a.load(s(0xB1)); a.w(0x0A03); a.jump(f'off_{row}', 'BZ')
        a.load(s(0xB1)); a.w(0x0900); a.jump(f'blank_{row}', 'BZ')
        a.movff(s(0x61), 0x13); a.w(0x0100); a.call(0x6F44)
        a.load(s(0xB1)); a.w(0x0A02); a.jump(f'row_done_{row}', 'BNZ')
        a.put(0x0D, 0x88); a.put(0x0E, numeric); a.put(0x0F, 2)
        a.w(0x0100); a.call(0x6520); a.jump(f'row_done_{row}')
        a.label(f'off_{row}'); a.put(0x13, 25); a.jump(f'blank_call_{row}')
        a.label(f'blank_{row}'); a.put(0x13, 26)
        a.label(f'blank_call_{row}'); a.w(0x0100); a.call(0x90F4)
        a.label(f'row_done_{row}')
    # Fixed A/B/C symbols cannot be relabelled in firmware; blank on DEF.
    for bit in (0, 2, 4):
        a.bit(0x88, bit, 'clear')
    a.load(s(3)); a.w(0x0900); a.jump('page_symbols_done', 'BNZ')
    for bit in (0, 2, 4):
        a.bit(0x88, bit, 'set')
    a.label('page_symbols_done')
    for row, bit in ((1, 1), (2, 3), (3, 5)):
        a.bit(0x88, bit, 'clear')
        a.load(s(4)); a.w(0x0A07); a.jump(f'selected_{row}', 'BZ')
        a.load(s(4)); a.w(0x0A00 | row); a.jump(f'select_done_{row}', 'BNZ')
        a.label(f'selected_{row}'); a.bit(0x88, bit, 'set')
        a.label(f'select_done_{row}')
    a.load(s(5)); a.store(s(0xB2))
    a.load(s(6)); a.w(0x0100 | (s(0xB2) >> 8)); a.w(0x1500 | (s(0xB2) & 255)); a.store(s(0xB2))
    a.load(s(3)); a.w(0x0900); a.jump('model_page_ready', 'BZ')
    for _ in range(3):
        a.w(0x0100 | (s(0xB2) >> 8)); a.w(0x4300 | (s(0xB2) & 255))
    a.label('model_page_ready')
    for sourcebit, displaybit in ((0, 4), (1, 6), (2, 7)):
        a.bit(0x8F, displaybit, 'clear')
        a.bit(s(0xB2), sourcebit, 'skip_set'); a.jump(f'model_icon_skip_{sourcebit}')
        a.bit(0x8F, displaybit, 'set'); a.label(f'model_icon_skip_{sourcebit}')
    # A short native-clock page label makes fixed glass A/B/C unambiguous.
    # B4..B7 are initialized by startup_hook, outside shared-core ownership.
    a.load(s(3)); a.w(0x0100 | (s(0xB4) >> 8)); a.w(0x1900 | (s(0xB4) & 255))
    a.jump('hint_page_unchanged', 'BZ')
    a.movff(s(3), s(0xB4)); a.put(s(0xB5), 1)
    a.movff(0x11B, s(0xB6)); a.movff(0x11C, s(0xB7))
    a.label('hint_page_unchanged')
    a.load(s(0xB5)); a.w(0x0900); a.jump('hint_done', 'BZ')
    a.load(s(0xB6)); a.w(0x0101); a.w(0x5D1B); a.store(s(0xB8))
    a.load(s(0xB7)); a.w(0x0101); a.w(0x591C); a.store(s(0xB9))
    a.lit(hint_counts & 255); a.w(0x0100 | (s(0xB8) >> 8)); a.w(0x5D00 | (s(0xB8) & 255))
    a.lit(hint_counts >> 8); a.w(0x0100 | (s(0xB9) >> 8)); a.w(0x5900 | (s(0xB9) & 255))
    a.jump('hint_expired', 'BC')
    for row, numeric in ((1,0x89),(2,0x8B),(3,0x8D)):
        a.put(0x11,0x88); a.put(0x12,numeric); a.put(0x13,26)
        a.w(0x0100); a.call(0x90F4)
        a.load(s(3)); a.w(0x0900); a.jump(f'hint_abc_{row}', 'BZ')
        a.lit(12+row); a.jump(f'hint_glyph_{row}')
        a.label(f'hint_abc_{row}'); a.lit(9+row)
        a.label(f'hint_glyph_{row}'); a.store(0x0F); a.put(0x0E,numeric)
        a.w(0x0100); a.call(0x9D76)
    a.jump('hint_done')
    a.label('hint_expired'); a.put(s(0xB5),0)
    a.label('hint_done')
    a.ret()

    a.label('tx_frame')
    a.call(a.labels['read_inputs']); a.w(0x0900); a.jump('tx_refused', 'BZ')
    a.load(s(0x77)); a.w(0x0B82); a.w(0x0A82); a.jump('tx_refused', 'BNZ')
    # Native queue pointer is only 8 bits; bridge via its original buffer.
    for i in range(16):
        a.movff(s(0x30 + i), 0x1D + i)
    a.put(0x18, 0x1D); a.w(0x0100); a.call(0x9D54); a.ret()
    a.label('tx_refused'); a.ret(0)

    a.label('nv_load'); a.ret(0)
    a.label('nv_commit'); a.ret(0)
    blob = a.finalize()
    if code_base + len(blob) >= 0xF800:
        raise ValueError('backend exceeds proposed code limit')
    blank = original[code_base - app_base:code_base - app_base + len(blob)]
    if len(blank) != len(blob) or any(x != 0xFF for x in blank):
        raise ValueError('backend is not in proved erased stock code tail')
    return {
        'sections': [{'address': code_base, 'data': blob, 'role': 'N_native_backend'}],
        'hooks': [],
        'exports': {name: a.labels[name] for name in MANDATORY},
        'labels': dict(a.labels),
        'reserved_ram': [{'start': state_base + 0xB0, 'end': state_base + 0x180, 'owner': 'N_provider'}],
        'required_imports': ['display_row'],
        'unresolved_imports': [] if display else ['display_row'],
        'metadata': {
            'model_tag': 'N', 'stock_sha256': STOCK_SHA256,
            'status': 'OFFLINE_BACKEND_REPLAY_REQUIRED', 'nv_enabled': False,
            'ram_proven': False, 'native_hook_binding_complete': False,
            'different_mode_write_enabled': True,
            'page_hint_counts': hint_counts,
            'native_nv_readiness_enabled': nv_ready_enabled,
            'original_hss_code_modified': False,
            'limitations': ['NVM disabled pending geometry and journal proof',
                           'outer event/display/service hooks not emitted here',
                           'physical RAM and complete dynamic non-overlap proof required',
                           'page hint uses native counts; physical duration follows clock proof'],
        },
    }
