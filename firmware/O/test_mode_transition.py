#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Offline original-byte evidence for Olympus A4 boot mode projection.

No firmware output, hardware model, USB, or native executable is involved.
The Python wrapper describes sequencing; all mode/timer/callback/display,
record pack/unpack and pending-send bodies execute recovered PIC18 bytes.
"""
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'shared')]
from native_contract import stock, initialize_radio_ring
from pic18_vm import CPU

CALLBACKS = {
    0: {1: 0x8A4C, 2: 0x814E, 3: 0x8BAA, 7: 0xABC0},
    1: {1: 0x90AE, 2: 0x9072, 3: 0x9036, 7: 0x6930},
}
MODE_ROOTS = (0x6A62, 0x9B54, 0x9B28, 0x9AFC, 0x9B80)
SKIPS = {'BTFSC', 'BTFSS', 'CPFSLT', 'CPFSEQ', 'CPFSGT', 'TSTFSZ',
         'DECFSZ', 'INCFSZ', 'INFSNZ', 'DCFSNZ'}


def closure(cpu, roots, forced=None):
    """Both conditional/skip edges; direct calls include callee and return site.

    The four mode callback roots close the single PUSH/TOS dispatch at 6AA8.
    Forced edges are justified constants, not general branch simplification:
    85EE falls through with inhibit=1; 6BAA falls through for timer input zero.
    """
    forced = forced or {}
    found, pending = {}, list(roots)
    while pending:
        pc = pending.pop()
        if pc in found:
            continue
        ins = cpu.decode(pc)
        found[pc] = ins
        nxt = pc + ins.length
        if pc in forced:
            pending.extend(forced[pc])
        elif ins.mnemonic in ('RETURN', 'RETFIE', 'RETLW'):
            continue
        elif ins.mnemonic in ('GOTO', 'BRA'):
            pending.append(ins.target)
        elif ins.target is not None:
            pending.extend((ins.target, nxt))
        elif ins.mnemonic in SKIPS:
            pending.extend((nxt, nxt + cpu.decode(nxt).length))
        else:
            pending.append(nxt)
    return found


def direct_2a_instructions(decoded):
    out = []
    for pc, ins in decoded.items():
        if ins.mnemonic == 'MOVFF':
            if 0x02A in ins.args:
                out.append(pc)
        elif ins.mnemonic not in ('LFSR', 'MOVLW', 'ADDLW', 'RETLW',
                                   'SUBLW', 'ANDLW', 'XORLW', 'IORLW',
                                   'MULLW', 'MOVLB'):
            if ins.args and ins.args[0] == 0x2A:
                out.append(pc)
    return sorted(out)


def make_cpu(mode=0, group=1, sync=2, fec=(-20, 0, 20)):
    image, mask = stock()
    cpu = CPU(image, mask=mask)
    cpu.track_trace = True
    cpu.m[0x7E:0x80] = bytes((0x99, 1))
    cpu.m[0x199:0x1A2] = bytes((mode, 0, sync, 30,
                              *(v & 255 for v in fec), 0, 0))
    cpu.m[0x36:0x39] = bytes((1, 2, 3))
    cpu.m[0x2C] = 7
    cpu.m[0x61] = 9
    cpu.m[0x29] = 1
    cpu.m[0xAD:0xAF] = bytes((0x34, 0x12))
    initialize_radio_ring(cpu)
    cpu.m[0xFE0] = 0
    cpu.w = group
    cpu.run(0x609A, max_steps=10000)
    cpu.trace.clear()
    cpu.events.clear()
    cpu.writes.clear()
    return cpu


class ModeTransitionTests(unittest.TestCase):
    def test_original_mode_body_96_combinations(self):
        count = 0
        for old in (0, 1):
            for group in (1, 2, 3, 7):
                for sync in range(4):
                    for fec in ((-20, 0, 20), (0, 0, 0), (20, -20, 10)):
                        with self.subTest(old=old, group=group, sync=sync, fec=fec):
                            c = make_cpu(old, group, sync, fec)
                            before = bytes(c.m)
                            c.m[0x2A] = 1
                            c.run(0x6A62, max_steps=10000)
                            self.assertEqual(c.m[0x199], 1-old)
                            self.assertEqual(c.m[0x61], 0)
                            self.assertEqual(c.m[0x29], 0)
                            self.assertEqual(c.m[0xAD:0xAF], b'\xff\xff')
                            self.assertEqual(c.m[0x2A], 1)
                            self.assertEqual(c.m[0x19B], 3 if old == 1 and sync == 2 else sync)
                            self.assertEqual(int.from_bytes(c.m[0x69:0x6C], 'little'), CALLBACKS[1-old][group])
                            self.assertEqual(c.m[0x95:0x9B], before[0x95:0x9B])
                            self.assertEqual(c.m[0x300:0x364], before[0x300:0x364])
                            self.assertFalse(c.events)
                            self.assertFalse({0x9F1E, 0x7112, 0x7108, 0xA76A} & set(c.trace))
                            # Recovered IRQ shared state must not be rolled back.
                            for a, b in ((0x40, 0x41), (0x81, 0x82), (0x89, 0x8A),
                                         (0xB1, 0xB3), (0xB5, 0xB7), (0x19A, 0x19B),
                                         (0x1B2, 0x1B8), (0x215, 0x26F)):
                                self.assertEqual(c.m[a:b], before[a:b])
                            count += 1
        self.assertEqual(count, 96)

    def test_closed_irq_and_inhibited_mode_graph(self):
        image, mask = stock()
        c = CPU(image, mask=mask)
        irq = closure(c, (0x4108,))
        self.assertEqual(len(irq), 392)
        self.assertEqual(direct_2a_instructions(irq), [])
        self.assertFalse(any(i.mnemonic == 'PUSH' for i in irq.values()))
        mode = closure(c, MODE_ROOTS, {0x85EE: (0x85F0,), 0x6BAA: (0x6BAC,)})
        self.assertEqual(len(mode), 866)
        self.assertEqual(direct_2a_instructions(mode), [0x85EC])
        self.assertEqual([pc for pc, i in mode.items() if i.mnemonic == 'PUSH'], [0x6AA8])
        self.assertFalse({0x888C, 0x9F66, 0x9F6C, 0x7112, 0x9F1E} & mode.keys())

    def test_boot_projection_pending_and_one_native_ttl_send(self):
        # Mirrors the agreed boot-MODE operation. Runtime field-only apply
        # must not re-arm 085. New A1 and A2 both project to native MAN=1.
        for old in (0, 1):
            for new_mode in ('TTL', 'A1', 'A2'):
                target = 0 if new_mode == 'TTL' else 1
                with self.subTest(old=old, target=new_mode):
                    c = make_cpu(old)
                    c.m[0x85] = int(old == 0)
                    c.m[0x2A] = 1
                    if old != target:
                        c.run(0x6A62, max_steps=10000)
                    c.m[0x85] = int(target == 0)
                    c.m[0x2A] = 0
                    self.assertEqual(c.m[0x97], 0)
                    self.assertEqual(c.m[0x199], target)
                    self.assertFalse(c.events)
                    # Exercise the original pending body after its caller's
                    # ABB0 readiness condition. No oscillator is simulated.
                    c.run(0x5950, max_steps=100000)
                    first_queue = bytes(c.m[0x95:0x9B])
                    first_buffer = bytes(c.m[0x300:0x364])
                    self.assertEqual(c.m[0x85], 0)
                    self.assertEqual(c.m[0x97], 24 if target == 0 else 0)
                    c.run(0x5950, max_steps=100000)
                    self.assertEqual(c.m[0x95:0x9B], first_queue)
                    self.assertEqual(c.m[0x300:0x364], first_buffer)
                    if target == 0:
                        self.assertEqual(c.m[0x306], 0x25)

    def test_native_nvm_mode_round_trip_without_toggle(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                c = make_cpu(mode)
                c.m[0x1BC:0x1C0] = b'\xff' * 4
                c.m[0x1E:0x23] = bytes((0xB8, 1, 0xBC, 1, 4))
                c.run(0x99BE)
                c.m[0xDD:0xE1] = bytes((0xD2, 1, 0x99, 1))
                c.run(0xA69C)
                c.m[0x199] = 9
                c.m[0x19B] = 9
                c.m[0x19D:0x1A0] = b'\0\0\0'
                c.trace.clear()
                c.m[0xDD:0xE1] = bytes((0x99, 1, 0xD2, 1))
                c.run(0xA66C)
                self.assertEqual(c.m[0x199], mode)
                self.assertEqual(c.m[0x19B], 2)
                self.assertEqual(c.m[0x19D:0x1A0], bytes((236, 0, 20)))
                self.assertNotIn(0x6A62, c.trace)
                self.assertFalse(c.events)


if __name__ == '__main__':
    unittest.main(verbosity=2)
