#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Relocatable AIR2 V5 two-page journal; emits PIC18 instructions only.

No native policy, device access, historical records, or fixed Canon state is used.
The generic assembler primitives derive from the authored P8 Asm helpers; this
module is self-contained and never imports or invokes another policy construct.
"""
from __future__ import annotations

PAGES = (0xF800, 0xFC00)
PAGE_SIZE = 0x400
RECORD_SIZE = 32
FORMAT_VERSION = 5
CODE_LIMIT = 0xF800
REQUIRED_PROOFS = ('hardware_proven', 'ram_proven', 'pages_proven', 'isr_context_proven')


def words(*values):
    return b''.join(value.to_bytes(2, 'little') for value in values)


def absolute(opcode, address):
    if not 0 <= address <= 0x1FFFFE or address & 1:
        raise ValueError('PIC18 absolute target must be even and in program space')
    return words(opcode | ((address // 2) & 255), 0xF000 | (address // 512))


class _Asm:
    """Generic instruction emitter with fixed-width long conditional branches."""
    def __init__(self, base):
        self.base, self.data = base, bytearray()
        self.labels, self.fixups, self.notes = {}, [], []

    @property
    def pc(self):
        return self.base + len(self.data)

    def label(self, name):
        if name in self.labels:
            raise ValueError('duplicate assembler label: ' + name)
        self.labels[name] = self.pc

    def emit(self, raw, note):
        self.notes.append((self.pc, note, raw.hex(' ')))
        self.data.extend(raw)

    def w(self, value, note):
        self.emit(words(value), note)

    def call(self, address):
        self.emit(absolute(0xEC00, address), 'CALL %X' % address)

    def movff(self, source, destination):
        if not 0 <= source < 4096 or not 0 <= destination < 4096:
            raise ValueError('MOVFF operand outside data space')
        self.emit(words(0xC000 | source, 0xF000 | destination), 'MOVFF')

    def jump(self, name, kind='BRA'):
        if kind not in ('BRA', 'GOTO', 'CALL'):
            pairs = {'BZ': 0xE100, 'BNZ': 0xE000, 'BC': 0xE300,
                     'BNC': 0xE200, 'BN': 0xE700, 'BNN': 0xE600}
            self.w(pairs[kind] | 2, 'inverse %s over GOTO' % kind)
            kind = 'GOTO'
        self.fixups.append((len(self.data), self.pc, name, kind))
        self.emit(words(0, 0), '%s %s' % (kind, name))

    def finalize(self):
        for offset, _, name, kind in self.fixups:
            self.data[offset:offset + 4] = absolute(
                0xEC00 if kind == 'CALL' else 0xEF00, self.labels[name])
        return bytes(self.data)


def construct(original=None, *, code_origin=None, code_base=None, state_base=0x680,
              imports=None, profile=None, backend=None, app_base=0x4000):
    """Return sections/exports using the shared native ABI.

    A missing proof produces explicit refusing stubs, never a permissive default.
    `original`, when supplied, is app-relative and both pages must exist/all-FF.
    `imports['read_inputs']` refreshes native readiness before each flash command.
    A first pass may leave that import unresolved; it must be resolved to package.
    """
    if code_origin is None:
        code_origin = code_base
    if code_origin is None or code_origin & 1 or code_origin < app_base:
        raise ValueError('even explicit code_origin within the application is required')
    profile, backend = dict(profile or {}), dict(backend or {})
    imports = dict(imports or {})
    state_base = int(profile.get('state_base', state_base))
    tag = profile.get('model_tag', backend.get('model_tag'))
    if isinstance(tag, int):
        tag = chr(tag)
    if tag not in ('F', 'N', 'O', 'S'):
        raise ValueError('model_tag must be F/N/O/S')
    if not 0 <= state_base <= 0xD80:
        raise ValueError('state block must fit 12-bit RAM below SFR space')
    if (state_base + 0x80) >> 8 != (state_base + 0xAF) >> 8:
        raise ValueError('NV scratch 80..AF must fit one data bank')
    proof = dict(backend.get('persistence', backend))
    enabled = all(proof.get(k) is True for k in REQUIRED_PROOFS)
    if enabled:
        expected = {'flash_bytes': 0x20000, 'erase_bytes': 0x400,
                    'write_bytes': 2, 'eecon1': 0xFA6, 'eecon2': 0xFA7,
                    'wprog_bit': 5}
        if any(proof.get(k) != value for k, value in expected.items()):
            raise ValueError('proved PIC18 F/LF47J13/J53 flash geometry/registers required')
        if original is not None:
            start, end = PAGES[0] - app_base, PAGES[1] + PAGE_SIZE - app_base
            if start < 0 or end > len(original) or any(b != 255 for b in original[start:end]):
                raise ValueError('new journal pages must be complete, known, original FF')

    a = _Asm(code_origin)
    scratch = state_base + 0x80
    bank = scratch >> 8
    # 14 preserved architectural bytes; W is the documented scalar result.
    registers = (0xFD8, 0xFE0, 0xFE9, 0xFEA, 0xFE1, 0xFE2,
                 0xFD9, 0xFDA, 0xFF6, 0xFF7, 0xFF8, 0xFF5, 0xFF3, 0xFF4)
    context = tuple((reg, scratch + i) for i, reg in enumerate(registers))
    names = ('VALID BL BH SL SH PL PH COUNT N CL CH BITS TMP SOURCE '
             'QL QH EFFECT DL DH WL WH WI IRQ LO HI RESULT EECON TOUCHED').split()
    v = {name: scratch + 14 + i for i, name in enumerate(names)}
    v['SAVE_FSR2L'], v['SAVE_FSR2H'] = scratch + 42, scratch + 43
    if max(v.values()) > state_base + 0xAF:
        raise ValueError('NV scratch exceeds borrowed core range')
    buffer = state_base + 0x40

    def w(op, note=''): a.w(op, note)
    def lit(value): w(0x0E00 | value, 'MOVLW %02X' % value)
    def get(address): a.movff(address, 0xFE8); w(0x0900, 'IORLW 0')
    def put(address): a.movff(0xFE8, address)
    def setv(address, value): lit(value); put(address)
    def fop(op, address): w(op | 0x100 | (address & 255))
    def zero(address): fop(0x6A00, address)
    def inc(address): fop(0x2A00, address)
    def call(label): a.jump(label, 'CALL')
    def go(label): a.jump(label, 'GOTO')
    def branch(label, cond): a.jump(label, cond)
    def ret(value=None): w(0x0012 if value is None else 0x0C00 | value)
    def fsr2(address): a.emit(words(0xEE20 | (address >> 8), 0xF000 | (address & 255)), 'LFSR2')
    def ptr(lo='PL', hi='PH'):
        a.movff(v[lo], 0xFF6); a.movff(v[hi], 0xFF7); w(0x6AF8, 'CLRF TBLPTRU')
    def step(amount, lo='PL', hi='PH'):
        lit(amount); fop(0x2600, v[lo]); lit(0); fop(0x2200, v[hi])
    def eq(value, bad='record_bad'):
        w(0x0A00 | value); branch(bad, 'BNZ')
    def next_crc(): call('read_crc')
    def compare_byte(value): next_crc(); eq(value)
    def preserve():
        for reg, dest in context: a.movff(reg, dest)
        w(0x0100 | bank, 'MOVLB NV scratch')
        zero(v['TOUCHED'])

    if not enabled:
        a.label('nv_load'); ret(0)
        a.label('nv_commit'); ret(0)
    else:
        a.label('nv_load'); preserve(); call('scan')
        get(v['VALID']); branch('return_zero', 'BZ')
        call('copy_best'); go('return_one')

        a.label('nv_commit'); preserve()
        call('gate_irq_save'); w(0x0900); branch('return_zero', 'BZ'); call('irq_restore')
        # Never reissue a caller's in-progress Flash operation during restoration.
        get(0xFA6); put(v['EECON']); w(0x0B02); branch('return_zero', 'BNZ')
        setv(v['SOURCE'], 1); fsr2(buffer); call('validate_record')
        w(0x0900); branch('return_zero', 'BZ')
        call('scan'); get(v['VALID']); branch('commit_changed', 'BZ')
        # Compare logical payload, excluding only the assigned sequence.
        ptr('BL', 'BH'); fsr2(buffer)
        for index in range(28):
            w(0x0009, 'TBLRD*+')
            a.movff(0xFDE, 0xFE8)
            if index not in (4, 5):
                put(v['TMP']); a.movff(0xFF5, 0xFE8)
                fop(0x1800, v['TMP']); branch('commit_changed', 'BNZ')
        call('copy_best'); go('return_one')

        a.label('commit_changed')
        get(v['VALID']); branch('initial_page', 'BZ')
        get(v['BH']); w(0x0BFC); put(v['PH']); zero(v['PL']); go('locate_slot')
        a.label('initial_page'); zero(v['PL']); setv(v['PH'], 0xF8)
        a.label('locate_slot'); call('find_erased'); w(0x0900); branch('slot_ready', 'BNZ')
        get(v['VALID']); branch('no_valid_page', 'BZ')
        get(v['BH']); w(0x0BFC); w(0x0A04); put(v['PH']); zero(v['PL']); go('erase_target')
        a.label('no_valid_page'); zero(v['PL']); setv(v['PH'], 0xF8)
        a.label('erase_target'); call('erase_page'); w(0x0900); branch('return_zero', 'BZ')
        w(0x0A01); branch('return_two', 'BNZ')
        a.label('slot_ready'); a.movff(v['PL'], v['WL']); a.movff(v['PH'], v['WH'])
        get(v['VALID']); branch('sequence_initial', 'BZ')
        inc(v['SL']); branch('sequence_ready', 'BNZ'); inc(v['SH']); go('sequence_ready')
        a.label('sequence_initial'); zero(v['SL']); zero(v['SH'])
        a.label('sequence_ready'); a.movff(v['SL'], buffer + 4); a.movff(v['SH'], buffer + 5)
        call('crc_buffer'); a.movff(v['CL'], buffer + 28); a.movff(v['CH'], buffer + 29)
        fsr2(buffer); setv(v['WI'], 16)
        a.label('write_loop'); call('write_word'); w(0x0900); branch('return_zero', 'BZ')
        w(0x0A01); branch('return_two', 'BNZ')
        step(2, 'WL', 'WH'); fop(0x2E00, v['WI']); go('write_loop')
        go('return_one')

        a.label('return_zero'); setv(v['RESULT'], 0); go('restore')
        a.label('return_two'); setv(v['RESULT'], 2); go('restore')
        a.label('return_one'); setv(v['RESULT'], 1)
        a.label('restore'); get(v['TOUCHED']); branch('restore_registers', 'BZ')
        a.movff(v['EECON'], 0xFA6)
        a.label('restore_registers')
        for reg, dest in reversed(context): a.movff(dest, reg)
        a.movff(v['RESULT'], 0xFE8); ret()

        a.label('scan'); zero(v['VALID']); zero(v['PL']); setv(v['PH'], 0xF8); setv(v['COUNT'], 64)
        a.label('scan_loop'); w(0x0004, 'CLRWDT'); zero(v['SOURCE']); ptr(); call('validate_record')
        w(0x0900); branch('scan_next', 'BZ'); get(v['VALID']); branch('scan_accept', 'BZ')
        a.movff(v['QL'], v['DL']); get(v['SL']); fop(0x5E00, v['DL'])
        a.movff(v['QH'], v['DH']); a.movff(v['SH'], 0xFE8); fop(0x5A00, v['DH'])
        get(v['DH']); w(0x0B80); branch('scan_next', 'BNZ')
        get(v['DL']); fop(0x1000, v['DH']); branch('scan_next', 'BZ')
        a.label('scan_accept'); setv(v['VALID'], 1)
        for src, dst in (('PL', 'BL'), ('PH', 'BH'), ('QL', 'SL'), ('QH', 'SH')):
            a.movff(v[src], v[dst])
        a.label('scan_next'); step(32); fop(0x2E00, v['COUNT']); go('scan_loop'); ret()

        a.label('copy_best'); ptr('BL', 'BH'); fsr2(buffer); setv(v['N'], 32)
        a.label('copy_loop'); w(0x0009); a.movff(0xFF5, 0xFDE)
        fop(0x2E00, v['N']); go('copy_loop'); ret()

        a.label('validate_record'); setv(v['CL'], 255); setv(v['CH'], 255)
        compare_byte(0x41); compare_byte(0x32); compare_byte(5)
        next_crc(); put(v['EFFECT']); w(0x0802); branch('record_bad', 'BNC')
        next_crc(); put(v['QL']); next_crc(); put(v['QH'])
        for _ in range(6):
            next_crc(); branch('record_bad', 'BZ'); w(0x0864); branch('record_bad', 'BNC')
        for _ in range(2):
            next_crc(); w(0x0BC0); branch('record_bad', 'BNZ')
        next_crc(); w(0x0801); branch('record_bad', 'BNC')
        next_crc(); put(v['TMP']); branch('record_bad', 'BZ'); w(0x0802); branch('record_bad', 'BNC')
        get(v['EFFECT']); branch('last_manual_ok', 'BZ')
        fop(0x1800, v['TMP']); branch('record_bad', 'BNZ')
        a.label('last_manual_ok'); compare_byte(ord(tag)); setv(v['N'], 11)
        a.label('reserved_loop'); next_crc(); branch('record_bad', 'BNZ')
        fop(0x2E00, v['N']); go('reserved_loop')
        call('read_byte'); fop(0x1800, v['CL']); branch('record_bad', 'BNZ')
        call('read_byte'); fop(0x1800, v['CH']); branch('record_bad', 'BNZ')
        call('read_byte'); eq(0x5A); call('read_byte'); eq(0xA5); ret(1)
        a.label('record_bad'); ret(0)

        a.label('read_byte'); get(v['SOURCE']); branch('read_ram', 'BNZ')
        w(0x0009); a.movff(0xFF5, 0xFE8); w(0x0900); ret()
        a.label('read_ram'); a.movff(0xFDE, 0xFE8); w(0x0900); ret()
        a.label('read_crc'); call('read_byte'); put(v['TMP']); fop(0x1A00, v['CH']); setv(v['BITS'], 8)
        a.label('crc_bit'); w(0x90D8); fop(0x3600, v['CL']); fop(0x3600, v['CH'])
        branch('crc_no_xor', 'BNC'); lit(0x21); fop(0x1A00, v['CL']); lit(0x10); fop(0x1A00, v['CH'])
        a.label('crc_no_xor'); fop(0x2E00, v['BITS']); go('crc_bit'); get(v['TMP']); ret()
        a.label('crc_buffer'); setv(v['CL'], 255); setv(v['CH'], 255); setv(v['SOURCE'], 1)
        fsr2(buffer); setv(v['N'], 28)
        a.label('crc_buffer_loop'); call('read_crc'); fop(0x2E00, v['N']); go('crc_buffer_loop'); ret()

        a.label('find_erased'); setv(v['COUNT'], 32)
        a.label('find_slot'); ptr(); setv(v['N'], 32)
        a.label('find_byte'); w(0x0009); get(0xFF5); w(0x0AFF); branch('find_next', 'BNZ')
        fop(0x2E00, v['N']); go('find_byte'); ret(1)
        a.label('find_next'); step(32); fop(0x2E00, v['COUNT']); go('find_slot'); ret(0)

        a.label('erase_page'); get(v['PL']); branch('erase_bad', 'BNZ')
        get(v['PH']); w(0x0AF8); branch('erase_address_ok', 'BZ')
        get(v['PH']); w(0x0AFC); branch('erase_bad', 'BNZ')
        a.label('erase_address_ok'); call('gate_irq_save'); w(0x0900); branch('erase_bad', 'BZ'); ptr()
        w(0x9AA6); w(0x88A6); call('flash_unlock'); call('irq_restore')
        w(0xB6A6); go('erase_fault')
        # Every byte of the destination page is verified before programming.
        ptr(); setv(v['N'], 4); zero(v['BITS'])
        a.label('erase_verify'); w(0x0004); w(0x0009); get(0xFF5); w(0x0AFF); branch('erase_fault', 'BNZ')
        fop(0x2E00, v['BITS']); go('erase_verify'); fop(0x2E00, v['N']); go('erase_verify'); ret(1)
        a.label('erase_bad'); ret(0)
        a.label('erase_fault'); ret(2)

        a.label('write_word'); get(v['WH']); w(0x0BF8); w(0x0AF8); branch('write_bad', 'BNZ')
        get(v['WL']); w(0x0B01); branch('write_bad', 'BNZ')
        call('gate_irq_save'); w(0x0900); branch('write_bad', 'BZ'); ptr('WL', 'WH')
        a.movff(0xFDE, 0xFF5); a.movff(0xFF5, v['LO']); w(0x000D)
        a.movff(0xFDE, 0xFF5); a.movff(0xFF5, v['HI']); w(0x000C)
        w(0x98A6); w(0x8AA6); call('flash_unlock'); call('irq_restore')
        w(0xB6A6); go('write_fault')
        ptr('WL', 'WH'); w(0x0009); get(0xFF5); fop(0x1800, v['LO']); branch('write_fault', 'BNZ')
        w(0x0008); get(0xFF5); fop(0x1800, v['HI']); branch('write_fault', 'BNZ'); ret(1)
        a.label('write_bad'); ret(0)
        a.label('write_fault'); ret(2)

        a.label('gate_irq_save')
        a.movff(0xFF2, v['IRQ']); w(0x9EF2); w(0x9CF2)
        a.movff(0xFD9, v['SAVE_FSR2L']); a.movff(0xFDA, v['SAVE_FSR2H'])
        a.call(int(imports.get('read_inputs', 0)))
        a.movff(v['SAVE_FSR2L'], 0xFD9); a.movff(v['SAVE_FSR2H'], 0xFDA)
        w(0x0100 | bank); w(0x0A01); branch('gate_failed', 'BNZ')
        get(state_base + 0x77); w(0x0B84); w(0x0A84); branch('gate_failed', 'BNZ'); ret(1)
        a.label('gate_failed'); call('irq_restore'); ret(0)
        a.label('irq_restore')
        for bit in (6, 7):
            w(0xA100 | bit << 9 | (v['IRQ'] & 255), 'BTFSS saved IRQ enable')
            go('irq_restored_%d' % bit); w(0x80F2 | bit << 9)
            a.label('irq_restored_%d' % bit)
        ret()
        a.label('flash_unlock'); setv(v['TOUCHED'], 1)
        w(0x96A6); w(0x84A6); w(0x0004)
        lit(0x55); w(0x6EA7); lit(0xAA); w(0x6EA7); w(0x82A6)
        w(0x94A6); w(0x98A6); w(0x9AA6); ret()

    blob = a.finalize()
    if a.pc > min(CODE_LIMIT, int(profile.get('code_limit', CODE_LIMIT))):
        raise ValueError('persistence code crosses F800 journal boundary')
    metadata = {
        'nv_enabled': enabled, 'missing_proofs': [k for k in REQUIRED_PROOFS if proof.get(k) is not True],
        'code_range': [code_origin, a.pc], 'record_version': FORMAT_VERSION,
        'model_tag': tag, 'state_base': state_base, 'record_buffer': [buffer, buffer + 32],
        'borrowed_scratch': [scratch, state_base + 0xB0],
        'runtime_nvm_pages': [[p, p + PAGE_SIZE] for p in PAGES],
        'stock_journal_untouched': [0x1F800, 0x1FC00],
        'preserved_registers': list(registers),
        'result': 'W=1 available/durable; W=0 absent/refused/retry; W=2 erase/program/readback fault',
        'interrupts': 'restore each prior GIEH/GIEL; do not overwrite pending INTCON flags',
        'geometry_proof': proof, 'asm_labels': dict(a.labels),
    }
    return {'sections': [{'address': code_origin, 'data': blob, 'role': 'air2_persistence'}],
            'hooks': [], 'exports': {name: a.labels[name] for name in ('nv_load', 'nv_commit')},
            'reserved_ram': [{'start': scratch, 'end': state_base + 0xB0, 'owner': 'nv_call_borrow'}],
            'required_imports': ['read_inputs'] if enabled else [],
            'unresolved_imports': ['read_inputs'] if enabled and not imports.get('read_inputs') else [],
            'metadata': metadata}
