#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Real shared core + O backend/hooks + original helpers; no helper mocks."""
import sys
import unittest
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'shared'))
from model_adapter import construct
from native_contract import stock,initialize_radio_ring
from native_hooks import CONTEXT_REGS
from pic18_vm import CPU

B=0x680
ORIGINAL,MASK=stock()
PROFILE=dict(model_tag='O',state_base=B,state_span=0x180,code_limit=0xF800,
             window_counts=200,stable_counts=10,clock_mask=0x7FFF,
             nv_enabled=False,native_input_gate_proven=True,
             native_radio_gate_proven=True,native_mode_restore_proven=True)
MODEL=construct(ORIGINAL,profile=PROFILE)
IMAGE=bytearray(ORIGINAL)
for section in MODEL['sections']:
    o=section['address']-0x4000;IMAGE[o:o+len(section['data'])]=section['data']
for patch in MODEL['hooks']:
    o=patch['address']-0x4000;IMAGE[o:o+4]=bytes.fromhex(patch['new_hex'])
CORE=MODEL['exports']
BACKEND=MODEL['components']['backend']['exports']
HOOK=MODEL['components']['hooks']['exports']


def make():
    c=CPU(IMAGE,mask=MASK)
    c.m[0x40]=1;c.m[0x24]=3;c.m[0x199]=1;c.m[0x60]=7
    c.m[0x2C]=7;c.m[0x7E:0x80]=bytes((0x99,1))
    initialize_radio_ring(c)
    c.w=7;c.run(0x609A,max_steps=10000)
    c.run(BACKEND['backend_init'],max_steps=2000)
    c.run(CORE['init'],max_steps=30000)
    assert c.m[B]==0xA8
    return c


def tick(c,value): c.m[0x75:0x77]=int(value&0x7FFF).to_bytes(2,'little')


class CompleteModelTests(unittest.TestCase):
    def test_no_hss_or_other_native_bytes_changed_outside_declared_hooks(self):
        allowed=set()
        for patch in MODEL['hooks']:
            allowed.update(range(patch['address']-0x4000,patch['address']-0x4000+4))
        for offset in range(2,0xABF0-0x4000):
            if offset not in allowed:self.assertEqual(IMAGE[offset],ORIGINAL[offset])
        self.assertEqual(MODEL['unresolved_imports'],[])
        self.assertLess(MODEL['metadata']['code_range'][1],0xF800)

    def test_power_hook_updates_absolute_state_and_preserves_native_context(self):
        c=make();c.m[B+2]=2
        for i,address in enumerate(CONTEXT_REGS): c.m[address]=(i*37+11)&255
        # Only architecturally implemented bits may be round-tripped.
        c.m[0xFD8]&=0x1F;c.m[0xFE0]&=0x0F
        for high in (0xFEA,0xFE2,0xFDA):c.m[high]&=0x0F
        c.m[0xFF8]&=0x1F
        c.w=1
        before=bytes(c.m[address] for address in CONTEXT_REGS)
        c.run(0x86D6,max_steps=100000)
        self.assertEqual(c.m[B+8:B+14],bytes((51,51,51,50,50,50)))
        self.assertEqual(bytes(c.m[address] for address in CONTEXT_REGS),before)
        self.assertEqual(c.m[0x61],0) # no duplicate original relative transaction
        self.assertNotEqual(c.m[0xAD:0xAF],bytes(2)) # original idle rearmed
        self.assertEqual(c.events,[])

    def test_group_press_uses_core_and_preserves_context(self):
        c=make();c.m[0xF2:0xF4]=bytes((0x0C,1))
        before=bytes(c.m[address] for address in CONTEXT_REGS)
        c.run(0x5C12,max_steps=100000)
        self.assertEqual(c.m[B+4],1);self.assertEqual(c.m[0x60],1)
        self.assertEqual(bytes(c.m[address] for address in CONTEXT_REGS),before)
        self.assertEqual(c.m[0x97],0)

    def test_c_model_chord_switches_air2_without_native_model_toggle(self):
        c=make();tick(c,0);c.m[0x114]=1;c.m[0xF2:0xF4]=bytes((0x14,1))
        c.run(0x5C12,max_steps=100000)
        self.assertEqual(c.m[0x115]&0x30,0x30)
        self.assertEqual(c.m[B+2],1)
        c.m[0x118]=1
        for value in (10,20):
            tick(c,value);c.run(HOOK['service'],max_steps=100000)
        self.assertEqual(c.m[B+2],2)
        self.assertEqual(c.m[0x3F],0);self.assertEqual(c.m[0x97],0)
        c.m[0x114]=0;c.m[0x118]=0
        for value in (30,40):
            tick(c,value);c.run(HOOK['service'],max_steps=100000)
        self.assertEqual(c.m[B+0x18],0)

    def test_lcd_hook_overlays_before_native_memcmp(self):
        c=make();c.m[B+2]=2;c.m[B+8:B+11]=bytes((23,50,99))
        c.m[0x8A:0x95]=bytes(11);c.m[0x2C4:0x2CF]=bytes(11)
        # Real 5912 caller args: first8A, second2C4, length0B.
        c.m[0x1E:0x23]=bytes((0x8A,0,0xC4,2,11))
        c.run(HOOK['lcd'],max_steps=100000)
        self.assertNotEqual(c.w,0) # native caller will set original LCD dirty
        self.assertEqual(c.m[0x8B:0x91],bytes.fromhex('de 7c bd 6f fd 7d'))

    def test_ttl_def_air1_expires_on_original_deadline(self):
        c=make();c.m[0x199]=0;c.m[B+1]=0;c.m[B+2]=1;c.m[B+3]=1
        c.m[B+7]=0x38;c.m[B+0x11:B+0x14]=bytes((1,2,3))
        # Native inactive/expired sentinel returns through native732C, then
        # the hook disarms the same AD timer via original AA38.
        c.m[0xAD:0xAF]=b'\xff\xff'
        c.run(HOOK['service'],max_steps=100000)
        self.assertEqual(c.m[B+7],0)
        self.assertEqual(c.m[B+0x0E:B+0x14],bytes(6))
        self.assertEqual(c.m[0xAD:0xAF],bytes(2))
        self.assertEqual(c.m[0x97],0)


if __name__=='__main__':unittest.main(verbosity=2)
