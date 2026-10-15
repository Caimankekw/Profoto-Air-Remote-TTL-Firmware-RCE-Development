#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Small standalone PIC18 instruction emitter; no firmware policy or I/O."""


def words(*values):
    return b''.join(x.to_bytes(2, 'little') for x in values)


def absolute(op, address):
    if address & 1 or not 0 <= address <= 0x1FFFFE:
        raise ValueError('invalid absolute target')
    return words(op | ((address // 2) & 255), 0xF000 | (address // 512))


class Asm:
    def __init__(self, base):
        self.base, self.data, self.labels, self.fixups = base, bytearray(), {}, []
        self.notes = []

    @property
    def pc(self):
        return self.base + len(self.data)

    def label(self, name):
        if name in self.labels:
            raise ValueError('duplicate label')
        self.labels[name] = self.pc

    def emit(self, raw, note):
        self.notes.append((self.pc, note, raw.hex(' ')))
        self.data.extend(raw)

    def w(self, value, note):
        self.emit(words(value), note)

    def movff(self, source, destination):
        self.emit(words(0xC000 | source, 0xF000 | destination),
                  'MOVFF %03X,%03X' % (source, destination))

    def jump(self, name, kind='BRA'):
        if kind not in ('BRA', 'BZ', 'BNZ'):
            raise ValueError('unsupported branch')
        self.fixups.append((len(self.data), self.pc, name, kind))
        self.emit(words(0), kind + ' ' + name)

    def finalize(self):
        for offset, pc, name, kind in self.fixups:
            delta = (self.labels[name] - (pc + 2)) // 2
            if kind == 'BRA':
                if not -1024 <= delta <= 1023:
                    raise ValueError('BRA range')
                opcode = 0xD000 | (delta & 2047)
            else:
                if not -128 <= delta <= 127:
                    raise ValueError('conditional branch range')
                opcode = {'BZ': 0xE000, 'BNZ': 0xE100}[kind] | (delta & 255)
            self.data[offset:offset+2] = words(opcode)
        return bytes(self.data)
