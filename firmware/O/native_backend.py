#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Emit Olympus A4 native backend for shared AIR2 ABI v1.

This is a bounded adapter component, not an install image. Native hooks and
outer context preservation are owned by the companion O/native_hooks.py.
Unproved readiness stays disabled and NVM is refused without side effects.
"""
import hashlib
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_contract import IMAGE_SHA256, ENTRY, RAM


def absolute(op, address):
    if address & 1:
        raise ValueError('unaligned target')
    return (op | (address//2 & 255)).to_bytes(2,'little') + (0xF000 | address//512).to_bytes(2,'little')


class Asm:
    def __init__(self,base):
        self.base=base; self.data=bytearray(); self.labels={}; self.fixups=[]
    @property
    def pc(self): return self.base+len(self.data)
    def w(self,value): self.data.extend(value.to_bytes(2,'little'))
    def label(self,name):
        if name in self.labels: raise ValueError('duplicate '+name)
        self.labels[name]=self.pc
    def movff(self,s,d): self.w(0xC000|s); self.w(0xF000|d)
    def call(self,address): self.data.extend(absolute(0xEC00,address))
    def go(self,label,condition=None):
        # Fixed-width absolute branches avoid placement-dependent short ranges.
        if condition:
            self.w({'BZ':0xE102,'BNZ':0xE002,'BC':0xE302,'BNC':0xE202}[condition])
        self.fixups.append((len(self.data),label)); self.data.extend(bytes(4))
    def finish(self):
        for off,label in self.fixups:
            self.data[off:off+4]=absolute(0xEF00,self.labels[label])
        return bytes(self.data)


def construct(original, *, app_base=0x4000, code_base, profile, imports=None):
    """Return six backend exports. No original instruction is patched here.

    profile gate proofs are independently supplied, not inferred from flags.
    This allows exact instruction tests before a physical allocation is proven.
    """
    if app_base != 0x4000 or hashlib.sha256(original).hexdigest()!=IMAGE_SHA256:
        raise ValueError('wrong Olympus A4 image')
    if profile.get('model_tag')!='O': raise ValueError('not Olympus profile')
    b=int(profile['state_base'])
    if profile.get('state_span')!=0x180 or b<0x400 or b+0x180>0xF00:
        raise ValueError('invalid state ABI allocation')
    imports=dict(imports or {})
    unresolved=[] if imports.get('display_row') else ['display_row']
    display=imports.get('display_row',0x4000)
    input_proven=bool(profile.get('native_input_gate_proven',False))
    radio_proven=bool(profile.get('native_radio_gate_proven',False))
    nv_proven=bool(profile.get('native_nv_gate_proven',False))
    mode_proven=bool(profile.get('native_mode_restore_proven',False))
    a=Asm(code_base)
    def lit(v): a.w(0x0E00|(v&255))
    def put(addr): a.movff(0xFE8,addr)
    def get(addr): a.movff(addr,0xFE8); a.w(0x0900)
    def setv(addr,val): lit(val);put(addr)
    def bank0(): a.w(0x0100)
    def ret(v=None):
        bank0()
        if v is None: a.w(0x0012)
        else: a.w(0x0C00|v)
    def andv(v): a.w(0x0B00|v)
    def orv(v): a.w(0x0900|v)
    def xor(v): a.w(0x0A00|v)
    def bit_branch(addr,bit,label,set_to=True):
        get(addr);andv(1<<bit);a.go(label,'BNZ' if set_to else 'BZ')
    def mutate_bit(addr,bit,on):
        get(addr); (orv(1<<bit) if on else andv(255^(1<<bit)));put(addr)
    def safe_gate(refused):
        if not (input_proven and radio_proven):
            a.go(refused)
            return
        get(0x82);a.go(refused,'BNZ')
        get(0x40);xor(1);a.go(refused,'BNZ')
        get(0x19A);a.go(refused,'BNZ')
        get(0x81);a.go(refused,'BNZ')
        get(0x2D);a.go(refused,'BNZ')
        get(0x2A);a.go(refused,'BNZ')
        get(0x61);a.go(refused,'BNZ')
        get(0x97);a.go(refused,'BNZ')
        a.call(0xA838);a.w(0x0900);a.go(refused,'BZ')

    a.label('backend_init');bank0()
    for off in range(0xB0,0xD0): setv(b+off,0)
    ret(1)
    a.label('read_inputs');bank0()
    for offset in range(0x70,0x80): setv(b+offset,0)
    a.movff(0x199,b+0x70);a.movff(0x60,b+0x71)
    get(0x2C);andv(7);put(b+0x72)
    get(0x3F);andv(7);put(b+0x73)
    for i in range(3): a.movff(0x19D+i,b+0x74+i)
    a.movff(0x75,b+0x78);get(0x76);andv(0x7F);put(b+0x79)
    for name,bit in (('C',0),('model',1),('head',2)):
        get(RAM['keys'][name]);andv(1);a.go('raw_'+name+'_skip','BZ')
        get(b+0x7A);orv(1<<bit);put(b+0x7A);a.label('raw_'+name+'_skip')
    for slot in (0x100,0x104,0x108,0x10C,0x110,0x120,0x124,0x128,0x12C):
        get(slot);andv(1);a.go('raw_other_yes','BNZ')
    a.go('raw_other_done');a.label('raw_other_yes');setv(b+0x7B,1)
    a.label('raw_other_done')
    get(b+0x70);a.go('input_mode_ok','BZ');xor(1);a.go('input_invalid','BNZ')
    a.label('input_mode_ok')
    get(b+0x71)
    for row in (1,2,3,7):
        get(b+0x71);xor(row);a.go('input_valid','BZ')
    a.go('input_invalid');a.label('input_valid');setv(b+0x77,0x80)
    if input_proven:
        get(0x82);a.go('input_done','BNZ')
        get(0x40);xor(1);a.go('input_done','BNZ')
        get(0x19A);a.go('input_done','BNZ')
        get(0x81);a.go('input_done','BNZ')
        get(0x2D);a.go('input_done','BNZ')
        a.call(0xA838);a.w(0x0900);a.go('input_done','BZ')
        get(0x2A);a.go('input_done','BNZ')
        get(0x61);a.go('input_done','BNZ')
        get(0x97);a.go('input_done','BNZ')
        get(b+0x77);orv(1);put(b+0x77)
        if radio_proven:
            get(b+0x77);orv(2);put(b+0x77)
            if nv_proven:
                # Read live inputs after shared NV has masked IRQs. Cached
                # 040/19A can still describe idle with an unserviced IRQ.
                # 67EC treats F81.2 high as deselected; 686E clears cursor089.
                # 411A..4162 dispatch FF0.1/F9E.5/FA4.5. Do not clear them,
                # consume RX data, or require their interrupt enables here.
                get(0x89);a.go('input_done','BNZ')
                bit_branch(0xF81,2,'input_done',set_to=False)
                for address,bit in ((0xFF0,1),(0xF9E,5),(0xFA4,5)):
                    bit_branch(address,bit,'input_done')
                get(0x85);a.go('input_done','BNZ')
                get(b+0x18);a.go('input_done','BNZ')
                get(b+0x28);a.go('input_done','BNZ')
                for slot in range(0x100,0x130,4):
                    get(slot);a.go('input_done','BNZ')
                get(b+0x77);orv(4);put(b+0x77)
    a.label('input_done');ret(1)
    a.label('input_invalid');setv(b+0x77,0);ret(0)

    a.label('apply_native_state');put(b+0xB0);bank0()
    get(b+0xB0);andv(0xF0);a.go('apply_refused','BNZ')
    safe_gate('apply_refused')
    # Preflight every requested native field before the first mutation.
    get(0x199);a.go('apply_native_mode_range_ok','BZ');xor(1);a.go('apply_refused','BNZ')
    a.label('apply_native_mode_range_ok')
    get(b+1);a.go('apply_mode_range_ok','BZ');xor(1);a.go('apply_refused','BNZ')
    a.label('apply_mode_range_ok')
    bit_branch(b+0xB0,2,'apply_check_selector');a.go('apply_selector_range_ok')
    a.label('apply_check_selector')
    for row in (1,2,3,7):
        get(b+4);xor(row);a.go('apply_selector_range_ok','BZ')
    a.go('apply_refused');a.label('apply_selector_range_ok')
    bit_branch(b+0xB0,1,'apply_check_fec');a.go('apply_fec_range_ok')
    a.label('apply_check_fec')
    for i in range(3):
        get(b+0x14+i);a.w(0x0F14);a.w(0x0828);a.go('apply_refused','BNC')
    a.label('apply_fec_range_ok')
    bit_branch(b+0xB0,3,'apply_check_masks');a.go('apply_masks_range_ok')
    a.label('apply_check_masks')
    for offset in (5,6):
        get(b+offset);andv(0xC0);a.go('apply_refused','BNZ')
    a.label('apply_masks_range_ok')
    # Preserve native mode-transition side effects; no bare mode RAM store.
    bit_branch(b+0xB0,0,'apply_mode_requested')
    a.go('apply_mode_ok');a.label('apply_mode_requested')
    # A boot projection captured before a native camera-mode change must
    # refuse instead of overwriting the newer native mode or pending25 state.
    a.movff(b+0x70,0xFE8);a.w(0x0101);a.w(0x1999)
    a.w(0x0900);a.go('apply_refused','BNZ');bank0()
    a.movff(b+1,0xFE8);a.w(0x0101);a.w(0x1999) # XORWF 199,W,BANK1
    a.w(0x0900);a.go('apply_mode_same','BZ');bank0()
    if mode_proven:
        # Validate and bind the finite native selector callback set before the
        # original mode routine. 2A is not touched by the closed IRQ path.
        for row in (1,2,3,7):
            get(0x60);xor(row);a.go('apply_mode_selector_valid','BZ')
        a.go('apply_refused');a.label('apply_mode_selector_valid')
        get(0x60);bank0();a.call(0x609A)
        setv(0x2A,1);a.call(0x6A62);setv(0x2A,0)
    else:
        a.go('apply_refused')
    a.label('apply_mode_same');bank0()
    # MODE projection is requested only by core boot_projection. Preserve the
    # original one-shot deferred startup25 policy; do not enqueue here.
    get(0x199);a.go('apply_startup_man','BNZ');setv(0x85,1)
    a.go('apply_mode_ok');a.label('apply_startup_man');setv(0x85,0)
    a.label('apply_mode_ok')
    bit_branch(b+0xB0,1,'apply_fec');a.go('apply_selector')
    a.label('apply_fec')
    for i in range(3): a.movff(b+0x14+i,0x19D+i)
    a.label('apply_selector')
    bit_branch(b+0xB0,2,'apply_selector_yes');a.go('apply_masks')
    a.label('apply_selector_yes');get(b+4);bank0();a.call(0x609A)
    a.label('apply_masks')
    bit_branch(b+0xB0,3,'apply_masks_yes');ret(1)
    a.label('apply_masks_yes')
    for offset,addr in ((5,0x2C),(6,0x3F)):
        get(b+offset);andv(7);put(b+0xB1)
        get(addr);andv(0xF8);put(b+0xB2)
        a.movff(b+0xB1,0xFE8)
        a.w(0x0100|(b+0xB2)//256)
        a.w(0x1100|((b+0xB2)&255)) # IORWF scratch,W,BANKED
        put(addr);bank0()
    ret(1);a.label('apply_refused');ret(0)

    a.label('redraw');bank0()
    get(0x82);a.go('redraw_done','BNZ')
    # Page-change letter hint uses original fine counter units, not ms.
    get(b+0xB3);xor(0xA4);a.go('hint_initialized','BZ')
    setv(b+0xB3,0xA4);a.movff(b+3,b+0xB4);setv(b+0xB5,0)
    a.go('hint_checked')
    a.label('hint_initialized')
    a.movff(b+3,0xFE8);a.w(0x0100|(b+0xB4)//256)
    a.w(0x1900|((b+0xB4)&255));a.go('hint_same_page','BZ');bank0()
    a.movff(b+3,b+0xB4);setv(b+0xB5,1)
    a.movff(0x75,b+0xB6);get(0x76);andv(0x7F);put(b+0xB7)
    a.go('hint_checked')
    a.label('hint_same_page');bank0()
    get(b+0xB5);a.go('hint_checked','BZ')
    a.movff(0x75,b+0xB8);get(0x76);andv(0x7F);put(b+0xB9)
    a.movff(b+0xB6,0xFE8);a.w(0x0100|(b+0xB8)//256)
    a.w(0x5F00|((b+0xB8)&255)) # SUBWF elapsed.low,F,BANKED
    a.movff(b+0xB7,0xFE8);a.w(0x5B00|((b+0xB9)&255)) # SUBWFB high,F
    bank0();get(b+0xB9);andv(0x7F);a.go('hint_expire','BNZ')
    get(b+0xB8);a.w(0x08C7);a.go('hint_checked','BC') # <=199 native counts
    a.label('hint_expire');setv(b+0xB5,0)
    a.label('hint_checked');bank0()
    for local,row in enumerate(RAM['rows'],1):
        lit(local);a.call(display);put(b+0xB0);bank0()
        get(b+0xB0);a.go('draw_blank_%d'%local,'BZ')
        xor(3);a.go('draw_off_%d'%local,'BZ')
        setv(0xB7,0x8A);setv(0xB8,row);a.movff(b+0x61,0xB9)
        a.call(ENTRY['format_signed_tenths'])
        get(b+0xB0);xor(2);a.go('draw_done_%d'%local,'BNZ')
        setv(0x1E,0x8A);setv(0x1F,row);setv(0x20,2)
        a.call(ENTRY['write_sign']);a.go('draw_done_%d'%local)
        a.label('draw_blank_%d'%local)
        setv(0xB7,0x8A);setv(0xB8,row);setv(0xB9,26);a.call(0x94B8)
        a.go('draw_done_%d'%local)
        a.label('draw_off_%d'%local)
        setv(0xB7,0x8A);setv(0xB8,row);setv(0xB9,25);a.call(0x94B8)
        a.label('draw_done_%d'%local)
        # Selection outline is local to the visible page, while core ALL=7.
        mutate_bit(0x8A,2*local-1,False)
        get(b+4);xor(local);a.go('box_on_%d'%local,'BZ')
        get(b+4);xor(7);a.go('box_done_%d'%local,'BNZ')
        a.label('box_on_%d'%local);mutate_bit(0x8A,2*local-1,True)
        a.label('box_done_%d'%local)
        modelbit=(4,6,7)[local-1]
        mutate_bit(0x91,modelbit,False)
        get(b+3);a.go('model_def_%d'%local,'BNZ')
        bit_branch(b+5,local-1,'model_abc_head_%d'%local)
        a.go('model_done_%d'%local)
        a.label('model_abc_head_%d'%local)
        bit_branch(b+6,local-1,'model_on_%d'%local)
        a.go('model_done_%d'%local)
        a.label('model_def_%d'%local)
        bit_branch(b+5,local+2,'model_def_head_%d'%local)
        a.go('model_done_%d'%local)
        a.label('model_def_head_%d'%local)
        bit_branch(b+6,local+2,'model_on_%d'%local)
        a.go('model_done_%d'%local)
        a.label('model_on_%d'%local);mutate_bit(0x91,modelbit,True)
        a.label('model_done_%d'%local)
    # Hide the original fixed ABC label bits on DEF without changing modes.
    get(0x8A);andv(0xEA);put(0x8A)
    get(b+3);a.go('redraw_done','BNZ')
    get(0x8A);orv(0x15);put(0x8A)
    a.label('redraw_done')
    get(0x82);a.go('redraw_return','BNZ')
    get(b+0xB5);a.go('redraw_return','BZ')
    for local,row in enumerate(RAM['rows'],1):
        setv(0x1E,0x8A);setv(0x1F,row);setv(0x20,2);a.call(0x688E)
        get(b+3);a.go('hint_glyph_def_%d'%local,'BNZ')
        lit(9+local);a.go('hint_glyph_ready_%d'%local)
        a.label('hint_glyph_def_%d'%local);lit(12+local)
        a.label('hint_glyph_ready_%d'%local);put(0x20)
        setv(0x1F,row);a.call(0xA10E);lit(row);a.call(0x94E6)
        setv(0x1F,row+1);setv(0x20,26);a.call(0xA10E)
    a.label('redraw_return');ret(1)

    a.label('tx_frame');bank0()
    if radio_proven:
        safe_gate('tx_refused')
        for i in range(16): a.movff(b+0x30+i,0xC1+i)
        setv(0xBC,0xC1);a.call(ENTRY['radio_enqueue16']);ret()
    a.label('tx_refused');ret(0)
    for name in ('nv_load','nv_commit'):
        a.label(name);ret(0)
    data=a.finish()
    if a.pc>profile['code_limit']: raise ValueError('backend exceeds code allocation')
    return {'sections':[{'address':code_base,'data':data,'role':'olympus_native_backend'}],
            'hooks':[], 'exports':{name:a.labels[name] for name in
                       ('backend_init','read_inputs','apply_native_state','redraw','tx_frame','nv_load','nv_commit')},
            'labels':dict(a.labels),
            'required_imports':['display_row'],'unresolved_imports':unresolved,
            'reserved_ram':[{'start':b+0xB0,'end':b+0xBA,'owner':'olympus_backend_bridge_and_page_hint'}],
            'metadata':{'native_input_gate_proven':input_proven,
                        'native_radio_gate_proven':radio_proven,
                        'nv_enabled':False,'native_mode_change_supported':mode_proven,
                        'native_mode_restore_proven':mode_proven,
                        'native_boot_pending25_preserved':True,
                        'native_original_hss_bytes_modified':False,
                        'page_transition_letter_hint_implemented':True,
                        'page_hint_native_counts':200,
                        'native_nv_gate_proven':nv_proven,
                        'outer_native_hooks_implemented':False,
                        'state_base_is_proof_conditioned':True,
                        'native_queue_empty_required':True,
                        'radio_queue_is_not_rf_ack':True}}
