#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""In-memory F stock + shared core + UI hooks. No executable or HEX output."""
from pathlib import Path
import sys,json,hashlib
HERE=Path(__file__).resolve().parent;SHARED=HERE.parent/'shared'
sys.path[:0]=[str(HERE),str(SHARED)]
import native_backend,native_hooks,runtime_generator
from pic18_vm import CPU

def build():
    stock=(SHARED/'stock/F/original.base4000.partial.bin').read_bytes()
    mask=(SHARED/'stock/F/original.known_mask.bin').read_bytes()
    profile=dict(model_tag='F',state_base=0x680,state_span=0x180,window_counts=200,
                 stable_counts=10,clock_mask=0x7fff,code_limit=0xf800,ram_proven=True,
                 native_admission_proven=True,nv_enabled=False)
    backend=native_backend.construct(stock,code_base=0xb2e0,profile=profile,
                                     imports={'display_row':0xd000})
    corebase=backend['sections'][0]['address']+len(backend['sections'][0]['data'])
    core=runtime_generator.construct(stock,code_base=corebase,profile=profile,backend=backend)
    backend=native_backend.construct(stock,code_base=0xb2e0,profile=profile,imports=core['exports'])
    hookbase=core['sections'][0]['address']+len(core['sections'][0]['data'])
    hooks=native_hooks.construct(stock,code_base=hookbase,profile=profile,
                                 core=core['exports'],backend=backend['exports'])
    image=bytearray(stock);known=bytearray(mask)
    for obj in (backend,core,hooks):
        for s in obj['sections']:
            pos=s['address']-0x4000
            assert image[pos:pos+len(s['data'])]==b'\xff'*len(s['data'])
            image[pos:pos+len(s['data'])]=s['data'];known[pos:pos+len(s['data'])]=b'\1'*len(s['data'])
        for h in obj.get('hooks',[]):
            pos=h['address']-0x4000;expected=bytes.fromhex(h['expected_hex'])
            assert image[pos:pos+len(expected)]==expected
            image[pos:pos+len(expected)]=bytes.fromhex(h['new_hex'])
    end=max(s['address']+len(s['data']) for o in (backend,core,hooks) for s in o['sections'])
    assert end<=0xf800
    return image,known,profile,backend,core,hooks,end

def main():
    image,known,profile,backend,core,hooks,end=build();state=profile['state_base']
    values={0x22:0x8c,0x23:1,0x18c:1,0x60:1,0x29:7,0x38:0,
            0x190:0,0x191:0,0x192:0,0x3a:1,0xfa4:0,0xff0:0,
            0x92:0,0x93:0,0x94:0,0x95:100,0x96:0,0x97:5,
            0x106:0x10,0x107:0,0xfe:0x71}
    c=CPU(image,values,known,allowed_sfr=(0xfa4,0xff0));passed=[]
    c.run(core['exports']['init']);assert not c.events
    assert c.m[state]==0xa8
    passed.append('stock_plus_core_init_native_LCD_without_function_stubs')
    c.m[state+2]=2 # Canonical AIR2 test precondition.
    c.m[0xfe0]=0;c.w=1;c.run(0x8d7e)
    assert c.m[state+8]==51 and c.m[0xfe]==0x71
    assert c.m[0x61]==0 # No original relative path after handled edit.
    passed.append('original_power_entry_hook_edits_AIR2_without_duplicate_relative_path')
    c.run(core['exports']['service'])
    assert c.m[0x500:0x511]==bytes([0,0x27,255,255,255,1,17,51,50,50,50,50,50,7,0,0,0])
    passed.append('full_core_AIR2_absolute_frame_through_original_F_ring')
    c.m[0x94]=0;c.m[0x92]=0;c.m[0x93]=0
    c.m[0xea]=0x1a;c.m[0xeb]=1;c.m[0xfe0]=0;c.run(0x5e6a)
    assert c.m[state+4]==2 and c.m[0x60]==2
    passed.append('native_B_press_dispatch_selects_canonical_B')
    c.m[0xfe0]=0;c.run(0x742e);assert not c.events
    assert c.m[0xfe]==0x71
    passed.append('native_LCD_entry_no_recursive_hook_preserves_ISR_command')
    # Enter through the native mode/deadline path, not the expiry hook alone.
    c.m[state+2]=1;c.m[state+7]=63
    c.m[0x106:0x108]=(1601).to_bytes(2,'little')
    c.m[0xa6:0xa8]=(1600).to_bytes(2,'little');c.m[0xfe0]=0
    c.run(0x8618,stops=(0x8644,))
    assert c.m[state+7]==0
    passed.append('original_idle_expiry_entry_hides_AIR1_values')
    c.m[state+2]=2;c.m[state+3]=1;c.m[state+5]=63;c.m[state+6]=42
    c.m[state+0x17f]=0
    native_heads=c.m[0x29];native_models=c.m[0x38]
    c.run(backend['exports']['redraw'])
    assert [c.m[a]&127 for a in (0x88,0x8a,0x8c)]==[0x7a,0x1f,0x17]
    assert c.m[0x87]&0x15==0 and c.m[0x8e]&0xd0==0x90
    assert c.m[0x29]==native_heads and c.m[0x38]==native_models
    c.run(backend['exports']['redraw'])
    assert [c.m[a] for a in (0x88,0x8a,0x8c)]==[0xbd]*3
    passed.append('DEF_hint_values_model_icons_do_not_overwrite_camera_ABC_masks')
    report=dict(passed=len(passed),checks=passed,code_end=hex(end),nv_enabled=False,
                actual_original_helpers=True,no_function_stubs=True,
                VM_sha256=hashlib.sha256((SHARED/'pic18_vm.py').read_bytes()).hexdigest(),
                hardware_accessed=False,flashable=False,
                scope='Instruction replay with explicit native state/MMIO fixture; not physical RF/timing validation')
    (HERE/'integrated_hooks_test_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
