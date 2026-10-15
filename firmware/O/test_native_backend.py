#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay unmodified Olympus A4 helper code. No EXE, USB, RF or NVM writes."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'shared'))
sys.path.insert(0, str(HERE))
from pic18_vm import CPU
from native_contract import (ENTRY, RAM, SIGN, GLYPH_DIGITS, stock,
                             initialize_radio_ring, set_formatter_arguments,
                             clear_sign_arguments, cmd11_body)

IMAGE, MASK = stock()


def cpu():
    return CPU(IMAGE, mask=MASK)


class OriginalLCDTests(unittest.TestCase):
    def test_binary_to_bcd_all_supported_values(self):
        for value in range(101):
            c = cpu()
            c.w = value
            c.run(ENTRY['bcd_unsigned'], max_steps=1000)
            self.assertEqual(c.w, (value // 10 << 4) | (value % 10), value)
            self.assertEqual(c.events, [])

    def test_signed_formatter_all_rows_and_values(self):
        for row in RAM['rows']:
            for value in range(-99,101):
                with self.subTest(row=row, value=value):
                    c = cpu()
                    set_formatter_arguments(c, row, value)
                    c.run(ENTRY['format_signed_tenths'], max_steps=5000)
                    v = abs(value)
                    expected = (bytes((GLYPH_DIGITS[v//10] | 0x80,
                                       GLYPH_DIGITS[v%10])) if v < 100
                                else bytes((GLYPH_DIGITS[1], GLYPH_DIGITS[0])))
                    self.assertEqual(c.m[row:row+2], expected)
                    flags, minus, plus = SIGN[row]
                    expected_sign = minus if value < 0 else minus | plus if value > 0 else 0
                    self.assertEqual(c.m[flags] & (minus | plus), expected_sign)
                    self.assertEqual(c.events, [])

    def test_absolute_power_sign_clear_preserves_other_icons(self):
        for row in RAM['rows']:
            for value in (1,10,23,50,99,100):
                c = cpu()
                c.m[0x8A:0x95] = bytes((0x2B,0,0,0,0,0,0,0xF0,0x55,0xAA,0x33))
                before = bytes(c.m[0x8A:0x95])
                set_formatter_arguments(c,row,value)
                c.run(ENTRY['format_signed_tenths'], max_steps=5000)
                clear_sign_arguments(c,row)
                c.run(ENTRY['write_sign'], max_steps=1000)
                flags,minus,plus = SIGN[row]
                self.assertEqual(c.m[flags] & (minus|plus), 0)
                for address in range(0x8A,0x95):
                    if address in (row,row+1):
                        continue
                    mask = ~(minus|plus)&255 if address == flags else 255
                    self.assertEqual(c.m[address]&mask,before[address-0x8A]&mask)


class OriginalRadioTests(unittest.TestCase):
    def make_ring(self):
        c = cpu()
        initialize_radio_ring(c)
        self.assertEqual(c.m[0x95:0x9B],bytes((0,0,0,100,0,3)))
        return c

    def enqueue(self,c,body):
        c.m[0xC1:0xD1] = body
        c.m[0xBC] = 0xC1
        c.run(ENTRY['radio_enqueue16'],max_steps=10000)

    def test_cmd11_all_bytes_reach_native_ring(self):
        body = cmd11_body((0,1,42,127,254,255),0x3F,0x2A)
        c = self.make_ring()
        self.enqueue(c,body)
        self.assertEqual(c.w,1)
        self.assertEqual(c.m[0x300:0x311],b'\0'+body)
        self.assertEqual(c.m[0x95:0x98],bytes((17,0,17)))
        self.assertEqual(c.events,[])

    def test_admission_failure_does_not_partially_write_packet(self):
        body = cmd11_body((1,2,3,4,5,6),63,0)
        for count in (84,85,99,100):
            c = self.make_ring()
            c.m[0x95:0x98] = bytes((count%100,0,count))
            c.m[0x300:0x364] = bytes(range(100))
            before = bytes(c.m[0x300:0x364])
            self.enqueue(c,body)
            self.assertEqual(c.w,0,count)
            self.assertEqual(c.m[0x300:0x364],before)
            self.assertEqual(c.m[0x95:0x98],bytes((count%100,0,count)))

    def test_exact_remaining_capacity_and_wrap(self):
        body = cmd11_body((1,20,40,60,80,100),0x15,0x2A)
        for write,read,count in ((83,0,83),(94,84,10),(99,99,0)):
            c = self.make_ring()
            c.m[0x95:0x98] = bytes((write,read,count))
            c.m[0x300:0x364] = bytes([0xA5])*100
            self.enqueue(c,body)
            self.assertEqual(c.w,1)
            actual = bytes(c.m[0x300+(write+i)%100] for i in range(17))
            self.assertEqual(actual,b'\0'+body)
            self.assertEqual(c.m[0x95:0x98],bytes(((write+17)%100,read,count+17)))

    def test_real_prefix_is_rsgt1_and_advances_pointer(self):
        c = cpu()
        c.m[0xBC:0xBE] = bytes((0,4))
        c.run(ENTRY['radio_prefix'],max_steps=3000)
        self.assertEqual(c.m[0x400:0x405],b'RSGT1')
        self.assertEqual(c.m[0xBC:0xBE],bytes((5,4)))
        self.assertEqual(c.events,[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
