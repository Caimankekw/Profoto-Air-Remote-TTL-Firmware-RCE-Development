#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Execute emitted O backends and original LCD/queue helpers, offline only."""
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'shared'))
from native_contract import stock, initialize_radio_ring, cmd11_body
from native_backend import construct, Asm
from pic18_vm import CPU

BASE=0x680
ORIGINAL,MASK=stock()


def build(ready=True, mode_proven=False):
    profile={'model_tag':'O','state_base':BASE,'state_span':0x180,
             'code_limit':0xF000,'native_input_gate_proven':ready,
             'native_radio_gate_proven':ready,'native_mode_restore_proven':mode_proven}
    backend=construct(ORIGINAL,code_base=0xAC00,profile=profile,
                      imports={'display_row':0xF000})
    image=bytearray(ORIGINAL)
    for section in backend['sections']:
        off=section['address']-0x4000
        image[off:off+len(section['data'])]=section['data']
    # Explicit test-only core query driver, not a mocked native helper.
    a=Asm(0xF000)
    a.w(0x0A01);a.go('row1','BZ');a.w(0x0A03);a.go('row2','BZ')
    a.w(0x0E00);a.movff(0xFE8,BASE+0x61);a.w(0x0C03)
    a.label('row1');a.w(0x0E17);a.movff(0xFE8,BASE+0x61);a.w(0x0C02)
    a.label('row2');a.w(0x0EFB);a.movff(0xFE8,BASE+0x61);a.w(0x0C01)
    driver=a.finish();image[0xB000:0xB000+len(driver)]=driver
    return image,backend


def make(ready=True, mode_proven=False):
    image,backend=build(ready,mode_proven)
    c=CPU(image,mask=MASK)
    c.m[0x199]=1;c.m[BASE+0x70]=1;c.m[0x60]=7;c.m[0x24]=3;c.m[0x40]=1
    c.m[0x7E:0x80]=bytes((0x99,1))
    return c,backend['exports']


class NativeAdapterTests(unittest.TestCase):
    def test_default_unproved_readiness_is_disabled(self):
        c,e=make(False);c.run(e['read_inputs'],max_steps=10000)
        self.assertEqual(c.w,1);self.assertEqual(c.m[BASE+0x77],0x80)
        initialize_radio_ring(c);c.run(e['tx_frame'],max_steps=10000)
        self.assertEqual(c.w,0);self.assertEqual(c.m[0x97],0)

    def test_read_snapshot_fields_keys_and_independent_gates(self):
        for state,block,voltage,expected in ((0,0,3,0x83),(0,1,3,0x80),
                                             (1,0,3,0x80),(0,0,2,0x80)):
            c,e=make();c.m[0x82]=state;c.m[0x2A]=block;c.m[0x24]=voltage
            c.m[0x2C]=0xAD;c.m[0x3F]=0xFE
            c.m[0x19D:0x1A0]=bytes((236,0,20))
            c.m[0x75:0x77]=bytes((0xAB,0xFC))
            c.m[0x114]=1;c.m[0x118]=0x81;c.m[0x11C]=0x80;c.m[0x124]=1
            before=bytes(c.m[BASE:BASE+0x70])
            c.run(e['read_inputs'],max_steps=10000)
            self.assertEqual(c.w,1)
            self.assertEqual(c.m[BASE+0x70:BASE+0x7C],
                             bytes((1,7,5,6,236,0,20,expected,0xAB,0x7C,3,1)))
            self.assertEqual(c.m[BASE:BASE+0x70],before)
            self.assertEqual(c.events,[])

    def test_invalid_native_mode_fails_snapshot(self):
        c,e=make();c.m[0x199]=2;c.run(e['read_inputs'],max_steps=10000)
        self.assertEqual(c.w,0);self.assertEqual(c.m[BASE+0x77],0)

    def test_apply_preserves_abc_meaning_on_def(self):
        for selection in (1,2,3,7):
            c,e=make();c.m[BASE+1]=1;c.m[BASE+3]=1;c.m[BASE+4]=selection
            c.m[BASE+5]=0x2B;c.m[BASE+6]=0x15
            c.m[BASE+0x14:BASE+0x17]=bytes((20,236,7))
            c.m[0x2C]=0xB0;c.m[0x3F]=0xE0;c.w=15
            c.run(e['apply_native_state'],max_steps=15000)
            self.assertEqual(c.w,1)
            self.assertEqual(c.m[0x199],1)
            self.assertEqual(c.m[0x19D:0x1A0],bytes((20,236,7)))
            self.assertEqual(c.m[0x60],selection)
            self.assertEqual(c.m[0x2C],0xB3)
            self.assertEqual(c.m[0x3F],0xE5)
            self.assertEqual(c.m[0x97],0)
            self.assertEqual(c.events,[])

    def test_unclosed_mode_change_refused_before_other_writes(self):
        c,e=make();c.m[BASE+1]=0;c.m[BASE+4]=1;c.m[BASE+5]=63
        before=bytes(c.m[0x24:0xB7])+bytes(c.m[0x199:0x1A2])
        c.w=15;c.run(e['apply_native_state'],max_steps=10000)
        self.assertEqual(c.w,0)
        self.assertEqual(bytes(c.m[0x24:0xB7])+bytes(c.m[0x199:0x1A2]),before)

    def test_proved_boot_mode_restore_uses_native_callback_and_deferred25(self):
        for old in (0,1):
            for target in (0,1):
                for group in (1,2,3,7):
                    c,e=make(mode_proven=True);initialize_radio_ring(c)
                    c.m[0x199]=old;c.m[BASE+0x70]=old;c.m[0x60]=group;c.m[0x19B]=2
                    c.m[0x85]=1-old;c.m[BASE+1]=target;c.w=1
                    c.run(e['apply_native_state'],max_steps=15000)
                    self.assertEqual(c.w,1,(old,target,group))
                    self.assertEqual(c.m[0x199],target)
                    self.assertEqual(c.m[0x85],1-target)
                    self.assertEqual(c.m[0x2A],0)
                    self.assertEqual(c.m[0x95:0x98],bytes(3))
                    self.assertEqual(c.m[0x300:0x364],bytes(100))
                    self.assertEqual(c.events,[])

    def test_apply_gate_and_range_failures_are_atomic(self):
        for native,value in ((0x82,1),(0x2A,1),(0x97,1),(0x24,2),(0x199,2),(BASE+0x70,0),
                             (BASE+4,4),(BASE+0x14,21),(BASE+5,64)):
            c,e=make();c.m[BASE+1]=1;c.m[BASE+4]=1
            c.m[BASE+5]=63;c.m[BASE+6]=63;c.m[native]=value
            before=bytes(c.m[0x24:0xB7])+bytes(c.m[0x199:0x1A2])
            c.w=15;c.run(e['apply_native_state'],max_steps=10000)
            self.assertEqual(c.w,0,(native,value))
            self.assertEqual(bytes(c.m[0x24:0xB7])+bytes(c.m[0x199:0x1A2]),before)

    def test_render_core_kinds_and_page_projection(self):
        for page in (0,1):
            c,e=make();c.m[BASE+3]=page;c.m[BASE+4]=7
            c.m[BASE+5]=0x3F;c.m[BASE+6]=0x11
            native_masks=bytes(c.m[0x2C:0x40])
            c.run(e['redraw'],max_steps=15000)
            self.assertEqual(c.m[0x8B:0x91],bytes.fromhex('de 7c ef 3d 10 10'))
            self.assertEqual(c.m[0x8A]&0x3F,0x3F if page==0 else 0x2A)
            self.assertEqual(c.m[0x8A]&0xC0,0) # AIR2 row A has no plus sign
            self.assertEqual(c.m[0x91]&0x0F,2) # negative row B only
            self.assertEqual(c.m[0x91]&0xD0,0x10 if page==0 else 0x40)
            self.assertEqual(c.m[0x2C:0x40],native_masks)
            self.assertEqual(c.events,[])

    def test_page_letters_expire_on_original_counter(self):
        c,e=make();c.m[BASE+4]=7;c.m[BASE+5]=63
        c.run(e['backend_init'],max_steps=1000)
        c.run(e['redraw'],max_steps=15000)
        c.m[BASE+3]=1;c.m[0x75:0x77]=bytes((0xF0,0x7F))
        c.run(e['redraw'],max_steps=15000)
        self.assertEqual(c.m[0x8B:0x91],bytes.fromhex('7a 00 1f 00 17 00'))
        # Fifteen-bit clock wrap still expires only after 200 native counts.
        c.m[0x75:0x77]=bytes((0xB7,0))
        c.run(e['redraw'],max_steps=15000)
        self.assertEqual(c.m[0x8B:0x91],bytes.fromhex('7a 00 1f 00 17 00'))
        c.m[0x75]=0xB8;c.run(e['redraw'],max_steps=15000)
        self.assertEqual(c.m[0x8B:0x91],bytes.fromhex('de 7c ef 3d 10 10'))

    def test_tx_preserves_core_frame_and_retries_capacity(self):
        c,e=make();initialize_radio_ring(c)
        frame=cmd11_body((1,23,45,67,89,100),63,42)
        c.m[BASE+0x30:BASE+0x40]=frame
        c.m[0x95:0x98]=bytes((90,0,90))
        c.run(e['tx_frame'],max_steps=15000)
        self.assertEqual(c.w,0);self.assertEqual(c.m[0x97],90)
        initialize_radio_ring(c)
        c.run(e['tx_frame'],max_steps=15000)
        self.assertEqual(c.w,1);self.assertEqual(c.m[0x300:0x311],b'\0'+frame)
        self.assertEqual(c.m[BASE+0x30:BASE+0x40],frame)
        self.assertEqual(c.events,[])

    def test_nvm_stubs_do_not_touch_ram_or_program_latches(self):
        for entry in ('nv_load','nv_commit'):
            c,e=make();before=bytes(c.m[:0xF00]);c.run(e[entry],max_steps=100)
            self.assertEqual(c.w,0);self.assertEqual(c.m[:0xF00],before)
            self.assertEqual(c.latches,{})


if __name__=='__main__': unittest.main(verbosity=2)
