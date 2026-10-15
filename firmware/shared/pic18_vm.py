#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Bounded, standard-library PIC18 classic-instruction replay. No hardware I/O.

This is an instruction model, not a device, oscillator or interrupt simulator.
Unknown code, unsupported instructions and unprovided peripheral boundaries fail.
Table-write instructions only fill latches; no device-specific Flash controller
is silently supplied. See VM_README.zh-CN.md for the evidence boundary.
"""
from __future__ import annotations
from dataclasses import dataclass


class VMError(RuntimeError):
    pass


class UnknownCode(VMError):
    pass


class UnsupportedInstruction(VMError):
    pass


class PeripheralBoundary(VMError):
    pass


class StepLimit(VMError):
    pass


@dataclass(frozen=True)
class Instruction:
    address: int
    length: int
    word: int
    mnemonic: str
    args: tuple = ()
    target: int | None = None


FILE_DA = {
    0x0400: 'DECF', 0x1000: 'IORWF', 0x1400: 'ANDWF', 0x1800: 'XORWF',
    0x1C00: 'COMF', 0x2000: 'ADDWFC', 0x2400: 'ADDWF', 0x2800: 'INCF',
    0x2C00: 'DECFSZ', 0x3000: 'RRCF', 0x3400: 'RLCF', 0x3800: 'SWAPF',
    0x3C00: 'INCFSZ', 0x4000: 'RRNCF', 0x4400: 'RLNCF',
    0x4800: 'INFSNZ', 0x4C00: 'DCFSNZ', 0x5000: 'MOVF',
    0x5400: 'SUBFWB', 0x5800: 'SUBWFB', 0x5C00: 'SUBWF',
}
FILE_A = {
    0x0200: 'MULWF', 0x6000: 'CPFSLT', 0x6200: 'CPFSEQ',
    0x6400: 'CPFSGT', 0x6600: 'TSTFSZ', 0x6800: 'SETF',
    0x6A00: 'CLRF', 0x6C00: 'NEGF', 0x6E00: 'MOVWF',
}
LITERAL = {
    0x0800: 'SUBLW', 0x0900: 'IORLW', 0x0A00: 'XORLW', 0x0B00: 'ANDLW',
    0x0C00: 'RETLW', 0x0D00: 'MULLW', 0x0E00: 'MOVLW', 0x0F00: 'ADDLW',
}
BITS = {0x7000: 'BTG', 0x8000: 'BSF', 0x9000: 'BCF',
        0xA000: 'BTFSS', 0xB000: 'BTFSC'}
BRANCHES = ('BZ', 'BNZ', 'BC', 'BNC', 'BOV', 'BNOV', 'BN', 'BNN')
FIXED = {0x0000: 'NOP', 0x0003: 'SLEEP', 0x0004: 'CLRWDT',
         0x0005: 'PUSH', 0x0006: 'POP', 0x0007: 'DAW',
         0x0008: 'TBLRD*', 0x0009: 'TBLRD*+', 0x000A: 'TBLRD*-',
         0x000B: 'TBLRD+*', 0x000C: 'TBLWT*', 0x000D: 'TBLWT*+',
         0x000E: 'TBLWT*-', 0x000F: 'TBLWT+*', 0x00FF: 'RESET'}
FSRS = ((0xFE9, 0xFEA, 0xFEB), (0xFE1, 0xFE2, 0xFE3),
        (0xFD9, 0xFDA, 0xFDB))
INDIRECT = {first + off: (i, ('PLUSW', 'PREINC', 'POSTDEC', 'POSTINC', 'INDF')[off])
            for i, (_, _, first) in enumerate(FSRS) for off in range(5)}
ARCH_SFR = {0xFD8, 0xFE0, 0xFE8, *range(0xFF3, 0x1000)}
for _lo, _hi, _first in FSRS:
    ARCH_SFR.update((_lo, _hi, *range(_first, _first + 5)))
C, DC, Z, OV, N = 1, 2, 4, 8, 16
PC_MASK = 0x1FFFFF
TABLE_MASK = 0x3FFFFF


def signed(value, bits=8):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class _Operand:
    """Resolve one file operand once, including read/modify/write indexing."""
    def __init__(self, cpu, address):
        self.cpu = cpu
        self.post = None
        self.null = False
        if address in INDIRECT:
            i, mode = INDIRECT[address]
            p = cpu.get_fsr(i)
            if mode == 'PREINC':
                p = (p + 1) & 0xFFF
                cpu.set_fsr(i, p)
            effective = (p + signed(cpu.w)) & 0xFFF if mode == 'PLUSW' else p
            if mode in ('POSTINC', 'POSTDEC'):
                self.post = (i, (p + (1 if mode == 'POSTINC' else -1)) & 0xFFF)
            self.null = effective in INDIRECT
            # Changing an auto-index register through itself needs the device's
            # write-priority rule; fail instead of inventing an alias ordering.
            if mode != 'INDF' and effective in FSRS[i][:2]:
                raise VMError('auto-index aliases its own FSR at %03X' % effective)
            address = effective
        self.address = address

    def read(self):
        return 0 if self.null else self.cpu._read(self.address)

    def write(self, value):
        if not self.null:
            self.cpu._write(self.address, value)

    def finish(self):
        if self.post is not None:
            self.cpu.set_fsr(*self.post)
            self.post = None


class CPU:
    def __init__(self, image, values=None, mask=None, base=0x4000, flash=None,
                 xinst=False, *, strict_peripherals=True, allowed_sfr=(),
                 flash_mask=None, max_steps=800000, allow_continuation_nop=True):
        if xinst:
            raise UnsupportedInstruction('XINST profile is not implemented')
        self.base = base
        self.code = bytes(image)
        self.mask = bytes([1]) * len(image) if mask is None else bytes(mask)
        if len(self.code) != len(self.mask):
            raise ValueError('image and known-mask lengths differ')
        if base < 0 or base + len(image) > PC_MASK + 1:
            raise ValueError('program address range')
        self.flash = bytearray(b'\xff' * max(0x20000, base + len(image))) if flash is None else bytearray(flash)
        if flash is None:
            self.flash[base:base + len(image)] = image
            self.flash_mask = bytearray(len(self.flash))
            self.flash_mask[base:base + len(image)] = self.mask
        else:
            self.flash_mask = bytearray([1]) * len(self.flash) if flash_mask is None else bytearray(flash_mask)
            if len(self.flash_mask) != len(self.flash):
                raise ValueError('flash and flash_mask lengths differ')
        self.m = bytearray(0x1000)
        for address, value in (values or {}).items():
            if not 0 <= address < 0x1000:
                raise ValueError('data address outside 12-bit space')
            self.m[address] = value & 0xFF
        self.allowed_sfr = set(allowed_sfr) | {a for a in (values or {}) if a >= 0xF00}
        self.strict_peripherals = strict_peripherals
        self.allow_continuation_nop = allow_continuation_nop
        self.stack = []
        self.fast_shadow = None
        self.pc = 0
        self.trace = []
        self.events = []
        self.reads = []
        self.writes = []
        self.step_hooks = {}
        self.read_hooks = {}
        self.write_hooks = {}
        self.step_limit = max_steps
        self.steps = 0
        self.decode_cache = {}
        self.latches = {}
        self.wdt_count = 0
        self.track_trace = False
        self._pc_write = None
        self._status_before_instruction = None

    @property
    def w(self):
        return self.m[0xFE8]

    @w.setter
    def w(self, value):
        self.m[0xFE8] = value & 0xFF

    def get_fsr(self, index):
        lo, hi, _ = FSRS[index]
        return self.m[lo] | ((self.m[hi] & 15) << 8)

    def set_fsr(self, index, value):
        lo, hi, _ = FSRS[index]
        self.m[lo] = value & 255
        self.m[hi] = (value >> 8) & 15

    def address(self, f, bank):
        banked = bank in (1, True, 'BANKED')
        return ((self.m[0xFE0] & 15) << 8 | f) if banked else (f if f < 0x60 else 0xF00 | f)

    def _peripheral(self, address, direction):
        if self.strict_peripherals and address >= 0xF00 and address not in ARCH_SFR and address not in self.allowed_sfr:
            raise PeripheralBoundary('%s unprovided SFR %03X at PC %06X' % (direction, address, self.pc))

    def _read(self, address):
        if not 0 <= address < 4096:
            raise VMError('data read outside 12-bit space')
        if address in self.read_hooks:
            value = self.read_hooks[address](self)
            if not isinstance(value, int) or not 0 <= value <= 255:
                raise VMError('read hook must return one byte')
            self.events.append(('read_hook', self.pc, address, value))
        else:
            self._peripheral(address, 'read')
            if address == 0xFF9:
                p = (self.pc + 2) & PC_MASK
                self.m[0xFFA] = p >> 8 & 255
                self.m[0xFFB] = p >> 16 & 31
                value = p & 255
            elif address == 0xFFC:
                value = len(self.stack)
            elif address in (0xFFD, 0xFFE, 0xFFF):
                value = ((self.stack[-1] if self.stack else 0) >> ((address - 0xFFD) * 8)) & (31 if address == 0xFFF else 255)
            elif address == 0xFD8:
                value = self.m[address] & 31
            else:
                value = self.m[address]
        self.reads.append((address, value))
        return value

    def _write(self, address, value):
        value &= 255
        if not 0 <= address < 4096:
            raise VMError('data write outside 12-bit space')
        if address in self.write_hooks:
            self.events.append(('write_hook', self.pc, address, value))
            self.write_hooks[address](self, value)
        else:
            self._peripheral(address, 'write')
            if address == 0xFF9:
                self._pc_write = ((self.m[0xFFB] & 31) << 16 | self.m[0xFFA] << 8 | value) & ~1
            elif address == 0xFFC:
                depth = value & 31
                if value & 0xC0:
                    raise VMError('STKPTR overflow/underflow flags are not modeled')
                if depth > len(self.stack):
                    raise VMError('cannot expose uninitialized hardware return stack')
                del self.stack[depth:]
            elif address in (0xFFD, 0xFFE, 0xFFF):
                if not self.stack:
                    raise VMError('TOS write with empty stack')
                shift = (address - 0xFFD) * 8
                self.stack[-1] = ((self.stack[-1] & ~(255 << shift)) | value << shift) & PC_MASK
            else:
                if address == 0xFE0 or address in (x[1] for x in FSRS):
                    value &= 15
                if address in (0xFD8, 0xFFB):
                    value &= 31
                if address == 0xFF8:
                    value &= 63
                self.m[address] = value
        self.writes.append((address, value))

    def read(self, address):
        ref = _Operand(self, address)
        value = ref.read()
        ref.finish()
        return value

    def write(self, address, value):
        ref = _Operand(self, address)
        ref.write(value)
        ref.finish()

    def _fetch(self, address, count):
        offset = address - self.base
        if address & 1 or offset < 0 or offset + count > len(self.code):
            raise UnknownCode('unaligned/outside code %06X +%d' % (address, count))
        if not all(self.mask[offset:offset + count]):
            raise UnknownCode('unknown code bytes at %06X +%d' % (address, count))
        return self.code[offset:offset + count]

    def decode(self, pc):
        if pc in self.decode_cache:
            return self.decode_cache[pc]
        word = int.from_bytes(self._fetch(pc, 2), 'little')
        op, args, target, length = None, (), None, 2
        if word in FIXED:
            op = FIXED[word]
        elif word in (0x0010, 0x0011, 0x0012, 0x0013):
            op, args = ('RETFIE' if word < 0x12 else 'RETURN'), (word & 1,)
        elif word & 0xFF00 == 0x0100:
            op, args = 'MOVLB', (word & 15,)
        elif word & 0xF000 == 0xC000 or word & 0xFE00 == 0xEC00 or word & 0xFF00 == 0xEF00 or word & 0xFFC0 == 0xEE00:
            second = int.from_bytes(self._fetch(pc + 2, 2), 'little')
            if second & 0xF000 != 0xF000:
                raise UnknownCode('malformed long instruction at %06X' % pc)
            length = 4
            if word & 0xF000 == 0xC000:
                op, args = 'MOVFF', (word & 0xFFF, second & 0xFFF)
            elif word & 0xFFC0 == 0xEE00:
                index = (word >> 4) & 3
                if index == 3 or second & 0xFF00 != 0xF000:
                    raise UnsupportedInstruction('invalid LFSR at %06X' % pc)
                op, args = 'LFSR', (index, ((word & 15) << 8) | (second & 255))
            else:
                op = 'CALL' if word & 0xFE00 == 0xEC00 else 'GOTO'
                target = ((((second & 0xFFF) << 8) | (word & 255)) << 1) & PC_MASK
                args = ((word >> 8) & 1,) if op == 'CALL' else ()
        elif word & 0xF800 in (0xD000, 0xD800):
            op = 'BRA' if word & 0xF800 == 0xD000 else 'RCALL'
            target = (pc + 2 + 2 * signed(word & 0x7FF, 11)) & PC_MASK
        elif 0xE000 <= word <= 0xE7FF:
            op = BRANCHES[(word >> 8) & 7]
            target = (pc + 2 + 2 * signed(word & 255)) & PC_MASK
        elif word & 0xF000 in BITS:
            op = BITS[word & 0xF000]
            args = (word & 255, (word >> 9) & 7, (word >> 8) & 1)
        elif word & 0xFC00 in FILE_DA:
            op = FILE_DA[word & 0xFC00]
            args = (word & 255, (word >> 9) & 1, (word >> 8) & 1)
        elif word & 0xFE00 in FILE_A:
            op = FILE_A[word & 0xFE00]
            args = (word & 255, (word >> 8) & 1)
        elif word & 0xFF00 in LITERAL:
            op, args = LITERAL[word & 0xFF00], (word & 255,)
        elif 0xF000 <= word < 0xFFFF and self.allow_continuation_nop:
            op = 'NOP_CONTINUATION'
        if op is None:
            raise UnsupportedInstruction('unknown/erased opcode %04X at %06X' % (word, pc))
        row = Instruction(pc, length, word, op, args, target)
        self.decode_cache[pc] = row
        return row

    def _flags(self, value, mask=Z | N, carry=False, dc=False, ov=False):
        value &= 255
        bits = (C if carry else 0) | (DC if dc else 0) | (Z if value == 0 else 0) | (OV if ov else 0) | (N if value & 128 else 0)
        # When STATUS itself is the destination of a flag-affecting operation,
        # writes to all five flags are inhibited; only the ALU's defined flags
        # change. Use the instruction's old STATUS for unaffected flags.
        previous = self.m[0xFD8] if self._status_before_instruction is None else self._status_before_instruction
        self.m[0xFD8] = ((previous & ~mask) | (bits & mask)) & 31

    def _add(self, a, b, carry=0):
        total = a + b + carry
        r = total & 255
        return r, (total > 255, (a & 15) + (b & 15) + carry > 15,
                   bool((~(a ^ b) & (a ^ r)) & 128))

    def _sub(self, a, b, borrow=0):
        total = a - b - borrow
        r = total & 255
        return r, (total >= 0, (a & 15) >= (b & 15) + borrow,
                   bool(((a ^ b) & (a ^ r)) & 128))

    def _push(self, address):
        if len(self.stack) >= 31:
            raise VMError('hardware return stack overflow')
        self.stack.append(address & PC_MASK)

    def tblptr(self):
        return self.m[0xFF6] | self.m[0xFF7] << 8 | (self.m[0xFF8] & 63) << 16

    def set_tblptr(self, value):
        value &= TABLE_MASK
        self.m[0xFF6] = value & 255
        self.m[0xFF7] = value >> 8 & 255
        self.m[0xFF8] = value >> 16 & 63

    def run(self, pc, stops=(), max_steps=None):
        """Run until a top-level RETURN or an explicit stop. All calls are real
        unless the caller installs a recorded step_hooks replacement.
        max_steps bounds instructions in this invocation, not physical time.
        """
        limit = self.step_limit if max_steps is None else max_steps
        if limit <= 0:
            raise ValueError('positive step bound required')
        for _ in range(limit):
            self.pc = pc
            if pc in stops:
                return pc
            if pc in self.step_hooks:
                self.events.append(('step_hook', pc))
                self.step_hooks[pc](self)
                if not self.stack:
                    return pc
                pc = self.stack.pop()
                continue
            r = self.decode(pc)
            self.steps += 1
            if self.track_trace:
                self.trace.append(pc)
            self._pc_write = None
            op, a, nxt = r.mnemonic, r.args, pc + r.length
            oldw, oldstatus = self.w, self.m[0xFD8] & 31
            self._status_before_instruction = oldstatus
            oldc = int(bool(oldstatus & C))
            if op in ('NOP', 'NOP_CONTINUATION'):
                pass
            elif op == 'CLRWDT':
                self.wdt_count += 1
                self.events.append(('watchdog_clear', pc))
            elif op in ('SLEEP', 'RESET', 'RETFIE'):
                raise UnsupportedInstruction('%s needs an explicit device/interrupt model' % op)
            elif op == 'PUSH':
                self._push(pc + 2)
            elif op == 'POP':
                if not self.stack:
                    raise VMError('hardware stack underflow on POP')
                self.stack.pop()
            elif op == 'DAW':
                correction = (6 if (oldw & 15) > 9 or oldstatus & DC else 0) + (0x60 if oldw > 0x99 or oldc else 0)
                self.w = oldw + correction
                self._flags(self.w, C, bool(oldc or oldw > 0x99))
            elif op.startswith('TBL'):
                p = self.tblptr()
                if '+*' in op:
                    p = (p & 0x200000) | ((p + 1) & PC_MASK)
                if op.startswith('TBLRD'):
                    if p >= len(self.flash) or not self.flash_mask[p]:
                        raise UnknownCode('unknown table byte at %06X' % p)
                    self.m[0xFF5] = self.flash[p]
                else:
                    self.latches[p] = self.m[0xFF5]
                    self.events.append(('table_latch', pc, p, self.m[0xFF5]))
                if op.endswith('*+'):
                    p = (p & 0x200000) | ((p + 1) & PC_MASK)
                elif op.endswith('*-'):
                    p = (p & 0x200000) | ((p - 1) & PC_MASK)
                self.set_tblptr(p)
            elif op == 'MOVLB':
                self.m[0xFE0] = a[0]
            elif op == 'LFSR':
                self.set_fsr(a[0], a[1])
            elif op == 'MOVFF':
                if a[1] in (0xFF9, 0xFFD, 0xFFE, 0xFFF):
                    raise UnsupportedInstruction('MOVFF destination PCL/TOS is prohibited')
                self.write(a[1], self.read(a[0]))
            elif op in ('MOVLW', 'ADDLW', 'SUBLW', 'ANDLW', 'IORLW', 'XORLW', 'MULLW', 'RETLW'):
                literal = a[0]
                if op in ('MOVLW', 'RETLW'):
                    self.w = literal
                elif op in ('ADDLW', 'SUBLW'):
                    result, f = self._add(oldw, literal) if op == 'ADDLW' else self._sub(literal, oldw)
                    self.w = result
                    self._flags(result, 31, *f)
                elif op == 'MULLW':
                    product = oldw * literal
                    self.m[0xFF3], self.m[0xFF4] = product & 255, product >> 8
                else:
                    self.w = {'ANDLW': oldw & literal, 'IORLW': oldw | literal, 'XORLW': oldw ^ literal}[op]
                    self._flags(self.w)
                if op == 'RETLW':
                    if not self.stack:
                        return pc
                    nxt = self.stack.pop()
            elif op in FILE_DA.values():
                faddr, dest, bank = a
                ref = _Operand(self, self.address(faddr, bank))
                fvalue = ref.read()
                flagmask, arithmetic, skip = 0, (False, False, False), False
                if op in ('ADDWF', 'ADDWFC'):
                    result, arithmetic = self._add(fvalue, oldw, oldc if op == 'ADDWFC' else 0)
                    flagmask = 31
                elif op in ('SUBWF', 'SUBWFB', 'SUBFWB'):
                    lhs, rhs = (oldw, fvalue) if op == 'SUBFWB' else (fvalue, oldw)
                    result, arithmetic = self._sub(lhs, rhs, 0 if op == 'SUBWF' else 1 - oldc)
                    flagmask = 31
                elif op in ('INCF', 'DECF'):
                    result, arithmetic = self._add(fvalue, 1) if op == 'INCF' else self._sub(fvalue, 1)
                    flagmask = 31
                elif op in ('INCFSZ', 'INFSNZ', 'DECFSZ', 'DCFSNZ'):
                    result = (fvalue + (1 if op.startswith('IN') else -1)) & 255
                    skip = (result == 0) if op.endswith('SZ') else (result != 0)
                elif op in ('RLCF', 'RRCF', 'RLNCF', 'RRNCF'):
                    left = op in ('RLCF', 'RLNCF')
                    carryout = bool(fvalue & (128 if left else 1))
                    carryin = int(carryout) if 'NCF' in op else oldc
                    result = ((fvalue << 1) | carryin) & 255 if left else ((fvalue >> 1) | carryin << 7)
                    flagmask = Z | N | (0 if 'NCF' in op else C)
                    arithmetic = (carryout, False, False)
                elif op == 'SWAPF':
                    result = ((fvalue << 4) | (fvalue >> 4)) & 255
                else:
                    result = {'MOVF': fvalue, 'COMF': fvalue ^ 255,
                              'IORWF': fvalue | oldw, 'ANDWF': fvalue & oldw,
                              'XORWF': fvalue ^ oldw}[op]
                    flagmask = Z | N
                if dest:
                    ref.write(result)
                else:
                    self.w = result
                ref.finish()
                if flagmask:
                    self._flags(result, flagmask, *arithmetic)
                if skip:
                    nxt += self.decode(nxt).length
            elif op in FILE_A.values():
                faddr, bank = a
                ref = _Operand(self, self.address(faddr, bank))
                if op == 'MOVWF':
                    ref.write(oldw)
                elif op == 'CLRF':
                    ref.write(0)
                    self._flags(0, Z)
                elif op == 'SETF':
                    ref.write(255)
                else:
                    fvalue = ref.read()
                    if op == 'NEGF':
                        result, flags = self._sub(0, fvalue)
                        ref.write(result)
                        self._flags(result, 31, *flags)
                    elif op == 'MULWF':
                        product = oldw * fvalue
                        self.m[0xFF3], self.m[0xFF4] = product & 255, product >> 8
                    elif {'CPFSLT': fvalue < oldw, 'CPFSEQ': fvalue == oldw,
                          'CPFSGT': fvalue > oldw, 'TSTFSZ': fvalue == 0}[op]:
                        nxt += self.decode(nxt).length
                ref.finish()
            elif op in BITS.values():
                faddr, bit, bank = a
                ref = _Operand(self, self.address(faddr, bank))
                value = ref.read()
                if op == 'BSF':
                    ref.write(value | (1 << bit))
                elif op == 'BCF':
                    ref.write(value & ~(1 << bit))
                elif op == 'BTG':
                    ref.write(value ^ (1 << bit))
                elif bool(value & (1 << bit)) == (op == 'BTFSS'):
                    nxt += self.decode(nxt).length
                ref.finish()
            elif op in ('GOTO', 'BRA', 'CALL', 'RCALL'):
                if op in ('CALL', 'RCALL'):
                    self._push(nxt)
                    if op == 'CALL' and a[0]:
                        self.fast_shadow = (oldw, oldstatus, self.m[0xFE0])
                nxt = r.target
            elif op in BRANCHES:
                flag = {'BZ': Z, 'BNZ': Z, 'BC': C, 'BNC': C,
                        'BOV': OV, 'BNOV': OV, 'BN': N, 'BNN': N}[op]
                positive = op in ('BZ', 'BC', 'BOV', 'BN')
                if bool(oldstatus & flag) == positive:
                    nxt = r.target
            elif op == 'RETURN':
                if a[0]:
                    if self.fast_shadow is None:
                        raise VMError('RETURN FAST without supplied shadow context')
                    self.w, self.m[0xFD8], self.m[0xFE0] = self.fast_shadow
                if not self.stack:
                    return pc
                nxt = self.stack.pop()
            else:
                raise UnsupportedInstruction('unimplemented %s at %06X' % (op, pc))
            pc = self._pc_write if self._pc_write is not None else nxt
            if pc & 1 or not 0 <= pc <= PC_MASK:
                raise VMError('invalid program counter %X' % pc)
        raise StepLimit('step limit %d at %06X' % (limit, self.pc))
