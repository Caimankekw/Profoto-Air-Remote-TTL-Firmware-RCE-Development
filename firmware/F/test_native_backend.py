#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay generated bridge plus actual F A5 functions, without helper stubs."""
from pathlib import Path
import json, sys

HERE=Path(__file__).resolve().parent
SHARED=HERE.parent/'shared'
sys.path.insert(0,str(SHARED));sys.path.insert(0,str(HERE))
from pic18_vm import CPU
from native_backend import construct_primitives

def main():
    original=(SHARED/'stock/F/original.base4000.partial.bin').read_bytes()
    mask=(SHARED/'stock/F/original.known_mask.bin').read_bytes()
    state=0x680  # VM-only address, not a claim about device SRAM availability.
    build=construct_primitives(original,code_base=0xb400,state_base=state)
    image=bytearray(original);known=bytearray(mask)
    for s in build['sections']:
        pos=s['address']-0x4000
        image[pos:pos+len(s['data'])]=s['data'];known[pos:pos+len(s['data'])]=b'\1'*len(s['data'])
    passed=[]
    def cpu(values=None): return CPU(image,values,known,max_steps=100000)
    def run(c,name): c.run(build['exports'][name]);assert not c.events, c.events
    c=cpu({0x22:0x8c,0x23:1,0x18c:1,0x60:7,0x29:5,0x38:2,
           0x190:0xf6,0x191:0,0x192:20,0x106:0x34,0x107:0x12,
           0x11e:0xff,0x122:0x01,0x126:0,0x12a:1})
    run(c,'read_inputs')
    assert c.w==1 and c.m[state+0x70:state+0x7c]==bytes([1,7,5,2,246,0,20,128,52,18,3,1])
    passed.append('actual_native_RAM_snapshot_and_raw_chord_objects')
    for ptr,mode in ((0,1),(0x18c,2)):
        c=cpu({0x22:ptr&255,0x23:ptr>>8,0x18c:mode})
        run(c,'read_inputs');assert c.w==0 and c.m[state+0x77]==0
    passed.append('invalid_snapshot_fail_closed')
    frame=bytes([0x27,255,255,255,1,17,1,20,40,60,80,100,63,42,0,0])
    for count in (0,81,82,83,84,99,100):
        c=cpu({0x92:0,0x93:0,0x94:count,0x95:100,0x96:0,0x97:5})
        c.m[state+0x30:state+0x40]=frame
        run(c,'enqueue_preflight')
        if count+17<100:
            assert c.w==1 and c.m[0x94]==count+17
            assert c.m[0x500:0x511]==b'\0'+frame
        else:
            assert c.w==0 and c.m[0x94]==count and c.m[0x500:0x511]==b'\0'*17
        assert c.m[state+0x30:state+0x40]==frame
    passed.append('original_A60A_radio_queue_marker_and_16bytes_capacity_boundary')
    c=cpu();run(c,'tx_frame');assert c.w==0
    passed.append('unproved_ISR_admission_fail_closed')
    gated=construct_primitives(original,code_base=0xb400,state_base=state,enable_admission=True)
    gi=bytearray(original);gm=bytearray(mask)
    for s in gated['sections']:
        pos=s['address']-0x4000;gi[pos:pos+len(s['data'])]=s['data'];gm[pos:pos+len(s['data'])]=b'\1'*len(s['data'])
    idle={0x22:0x8c,0x23:1,0x18c:1,0x60:7,0x3a:1,
          0x92:0,0x93:0,0x94:0,0x95:100,0x96:0,0x97:5,
          0xfa4:0,0xff0:0}
    # These two SFRs are explicit fixture inputs, not a peripheral model or a
    # hidden function stub. The queued command still runs native instructions.
    for changed in ({},{0x7a:1},{0x28:1},{0x61:1},{0x85:1},{0x94:1},
                    {0x3a:0},{0x3a:2},{0xfa4:128},{0xff0:2},{0xff0:4}):
        c=CPU(gi,{**idle,**changed},gm,allowed_sfr=(0xfa4,0xff0))
        c.m[state+0x30:state+0x40]=frame
        c.run(gated['exports']['tx_frame'])
        assert not c.events
        if not changed:
            assert c.w==1 and c.m[0x500:0x511]==b'\0'+frame
        else:
            assert c.w==0 and c.m[0x94]==changed.get(0x94,0)
            assert c.m[0x500:0x511]==b'\0'*17
    passed.append('opt_in_native_admission_each_busy_and_pending_IRQ_gate')
    glyphs=original[0x41c9-0x4000:0x41c9-0x4000+16]
    for row,dest in ((1,0x88),(2,0x8a),(3,0x8c)):
        for value in (1,9,10,25,99,100):
            c=cpu({state+0x17c:row,state+0x61:value})
            c.w=2;run(c,'render_row');assert c.w==1
            if value<100:
                assert c.m[dest]==glyphs[value//10]|0x80
                assert c.m[dest+1]&0x7f==glyphs[value%10]
            else:
                assert c.m[dest]==glyphs[1] and c.m[dest+1]&0x7f==glyphs[0]
            flagaddr,mask=(0x87,0xc0) if row==1 else (0x8e,3 if row==2 else 12)
            assert c.m[flagaddr]&mask==0
    passed.append('original_tenths_formatter_absolute_0p1_through_10_all_rows_no_sign')
    for row in (1,2,3):
        for kind in (0,1,3):
            c=cpu({state+0x17c:row,state+0x61:246});c.w=kind
            run(c,'render_row');assert c.w==1
    passed.append('native_blank_signed_negative_and_HeadOFF_helpers_all_rows')
    saved=build['metadata']['context_saved_addresses']
    c=cpu({addr:(i*17+3)&255 for i,addr in enumerate(saved)})
    # BSR is architectural 4 bits and PCLATH/U are passive latch bytes here.
    c.m[0xfe0]=3
    for addr in (0xfea,0xfe2,0xfda):c.m[addr]&=15
    c.m[0xff8]&=63
    before={addr:c.m[addr] for addr in saved}
    run(c,'context_save')
    for addr in saved:c.m[addr]=0
    for addr in (0xfe,0x2b1,0x1da,0x1e0):c.m[addr]=0xa5
    run(c,'context_restore')
    assert {addr:c.m[addr] for addr in saved}==before
    assert all(c.m[addr]==0xa5 for addr in (0xfe,0x2b1,0x1da,0x1e0))
    passed.append('foreground_context_exact_restore_preserves_ISR_owned_command_FE')
    callbacks={1:{0:0x9166,1:0x9694},2:{0:0x875a,1:0x9658},
               3:{0:0x9122,1:0x961c},7:{0:0xb2b6,1:0x6f20}}
    for mode in (0,1):
        for selected in (1,2,3,7):
            values={**idle,state+1:mode,state+3:1,state+4:selected,state+0x70:1,
                    state+5:0b101010,state+6:0b010101,
                    state+0x14:10,state+0x15:246,state+0x16:0,
                    0xfe:0x77}
            c=CPU(image,values,known,allowed_sfr=(0xfa4,0xff0));c.w=15
            c.run(build['exports']['apply_native_state']);assert not c.events
            assert c.w==1 and c.m[0x18c]==mode and c.m[0x60]==selected
            assert int.from_bytes(c.m[0x69:0x6c],'little')==callbacks[selected][mode]
            assert c.m[0x190:0x193]==bytes([10,246,0])
            assert c.m[0x29]==2 and c.m[0x38]==5 # ABC, never DEF projection.
            assert c.m[0xfe]==0x77 and c.m[0x94]==0
    passed.append('canonical_ABC_apply_native_mode_callbacks_FEC_no_RF_or_ISR_FE_write')
    c=CPU(image,{**idle,state+1:0,state+4:1,state+0x70:0,
                 state+5:0,state+6:7,state+0x14:20},known,
          allowed_sfr=(0xfa4,0xff0))
    untouched=[0x18c,0x60,0x29,0x38,0x190,0x191,0x192,*range(0x63,0x6f)]
    before=[c.m[a]for a in untouched];c.w=15;c.run(build['exports']['apply_native_state'])
    assert c.w==0 and [c.m[a]for a in untouched]==before
    passed.append('new_native_mode_event_refuses_stale_projection_before_any_state_write')
    report=dict(passed=len(passed),checks=passed,no_helper_stubs=True,
                original_native_machine_code_executed=True,hardware_accessed=False,
                RAM_address_for_VM_only=hex(state),flashable=False)
    (HERE/'native_backend_test_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
