#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Olympus A4 outer AIR2 hooks with native caller context preservation.

This emits six exact checked hook sites plus bounded code sections.
No image/package is written, no device is accessed, and no HSS routine is
replaced. Caller restoration is separate from intentional native state edits.
"""
import hashlib
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from native_backend import Asm, absolute
from native_contract import IMAGE_SHA256

CONTEXT_REGS = (
    0xFE8,0xFD8,0xFE0,0xFE9,0xFEA,0xFE1,0xFE2,0xFD9,0xFDA,
    0xFF3,0xFF4,0xFF5,0xFF6,0xFF7,0xFF8,
    *range(0x1E,0x24),*range(0xB7,0x100),*range(0x1CE,0x1F1))
HOOKS = (
    (0x57BC,'9fec46f0','startup','CALL',0x57C0),
    (0x58E0,'d6ec3af0','service','CALL',0x58E4),
    (0x5912,'cdec42f0','lcd','CALL',0x5916),
    (0x5C12,'000e0001','press','GOTO',0x5C16),
    (0x7FBE,'12ec36f0','idle_deadline','GOTO',0x7FC2),
    (0x86D6,'0001ea6f','power','GOTO',0x86DA),
)


def construct(original, *, app_base=0x4000, code_base, profile, imports):
    if app_base!=0x4000 or hashlib.sha256(original).hexdigest()!=IMAGE_SHA256:
        raise ValueError('wrong Olympus A4 stock')
    if profile.get('model_tag')!='O' or profile.get('state_span')!=0x180:
        raise ValueError('wrong target/state ABI')
    b=profile['state_base']
    if b<0x400 or b+0x180>0xF00: raise ValueError('invalid state range')
    if b+0xD0+len(CONTEXT_REGS)>b+0x180: raise ValueError('context overflow')
    needed=('init','service','power_edit','select_row','secondary_press',
            'idle_expired','backend_init','redraw')
    unresolved=[name for name in needed if not imports.get(name)]
    for address,preimage,_,_,_ in HOOKS:
        if original[address-app_base:address-app_base+4].hex()!=preimage:
            raise ValueError('hook preimage mismatch at %04X'%address)
    a=Asm(code_base)
    def call(name): a.call(imports.get(name,0x4000))
    def local_call(name):
        # Asm's normal fixup is a GOTO; reserve a separate CALL fixup here.
        call_fixups.append((len(a.data),name));a.data.extend(bytes(4))
    def ret(): a.w(0x0012)
    def get(addr): a.movff(addr,0xFE8);a.w(0x0900)
    def lit(value): a.w(0x0E00|value)
    def initialized(fallback):
        get(b);a.w(0x0AA8);a.go(fallback,'BNZ')
    def normal(fallback):
        get(0x82);a.go(fallback,'BNZ')
    def restore_return(): local_call('restore_context');ret()
    call_fixups=[]

    a.label('startup')
    a.call(0x8D3E);local_call('save_context')
    call('backend_init');call('init');restore_return()

    a.label('service')
    a.call(0x75AC);local_call('save_context')
    initialized('service_retry_init');a.go('service_initialized')
    a.label('service_retry_init');call('init');initialized('service_done')
    a.label('service_initialized');call('service')
    # Original MAN idle path reaches 7FBE. Extend only TTL/DEF AIR1 to the
    # same original AD:AE deadline; do not create a second elapsed-time policy.
    normal('service_done')
    get(b+1);a.go('service_redraw','BNZ')
    get(b+3);a.w(0x0A01);a.go('service_redraw','BNZ')
    get(b+2);a.w(0x0A01);a.go('service_redraw','BNZ')
    get(b+7);a.go('service_redraw','BZ')
    lit(0xAD);a.movff(0xFE8,0x22);lit(0);a.movff(0xFE8,0x23)
    a.call(0x732C);a.w(0x0900);a.go('service_redraw','BZ')
    call('idle_expired');a.w(0x0900);a.go('service_redraw','BZ')
    lit(0xAD);a.movff(0xFE8,0x1E);lit(0);a.movff(0xFE8,0x1F)
    a.call(0xAA38)
    a.label('service_redraw')
    # The later LCD hook owns final overlay: original timeout A7C2/9A48
    # between here and 5912 can otherwise overwrite all three values.
    a.label('service_done');restore_return()

    a.label('lcd');local_call('save_context')
    initialized('lcd_done');normal('lcd_done');call('redraw')
    a.label('lcd_done');local_call('restore_context')
    # Preserve the original memcmp parameters and its result/return flow.
    a.data.extend(absolute(0xEF00,0x859A))

    a.label('press');local_call('save_context')
    initialized('press_native');normal('press_native')
    get(0xF3);a.w(0x0A01);a.go('press_native','BNZ')
    for low,name in ((0x0C,'select_a'),(0x10,'select_b'),
                     (0x14,'secondary_c'),(0x18,'secondary_model'),(0x1C,'secondary_head')):
        get(0xF2);a.w(0x0A00|low);a.go(name,'BZ')
    a.go('press_native')
    for row,name in ((1,'select_a'),(2,'select_b')):
        a.label(name);lit(row);call('select_row');restore_return()
    for slot,value,name in ((0x114,1,'secondary_c'),(0x118,2,'secondary_model'),
                            (0x11C,4,'secondary_head')):
        a.label(name)
        # Native event flags b4 inhibits release, b5 inhibits both timed events.
        # History and timestamp remain owned by original 596E consumer.
        get(slot+1);a.w(0x0930);a.movff(0xFE8,slot+1)
        lit(value);call('secondary_press');restore_return()
    a.label('press_native');local_call('restore_context')
    a.w(0x0E00);a.w(0x0100);a.data.extend(absolute(0xEF00,0x5C16))

    a.label('power');local_call('save_context')
    initialized('power_native');normal('power_native')
    # Original W was captured in context slot0 before any gating instruction.
    a.movff(b+0xD0,0xFE8);call('power_edit')
    a.w(0x0900);a.go('power_handled_done','BZ')
    # Replacement path no longer drains native pending061. Rearm the same
    # original idle deadline after each accepted short/held power change.
    a.call(0x4A8E);a.call(0xA174);a.call(0x5D30)
    a.label('power_handled_done');restore_return()
    a.label('power_native');local_call('restore_context')
    a.w(0x0100);a.w(0x6FEA);a.data.extend(absolute(0xEF00,0x86DA))

    a.label('idle')
    a.call(0x6C24)
    a.label('idle_after_native');local_call('save_context')
    initialized('idle_done');normal('idle_done');call('idle_expired')
    a.label('idle_done');restore_return()

    a.label('idle_deadline');a.call(0x6C24);local_call('save_context')
    # Native 7FC2..7FC8 disarms AD:AE after the replaced idle call. Keep the
    # expired timer when visible AIR1 state cannot be cleared yet. The GOTO
    # entry/tail continuations leave the caller's hardware stack unchanged.
    initialized('idle_deadline_consume')
    get(b+2);a.w(0x0A01);a.go('idle_deadline_consume','BNZ')
    get(b+7);a.go('idle_deadline_consume','BZ')
    call('idle_expired');a.w(0x0900);a.go('idle_deadline_retry','BZ')
    local_call('restore_context');a.data.extend(absolute(0xEF00,0x7FC2))
    a.label('idle_deadline_consume');local_call('restore_context')
    local_call('idle_after_native');a.data.extend(absolute(0xEF00,0x7FC2))
    a.label('idle_deadline_retry');local_call('restore_context')
    a.data.extend(absolute(0xEF00,0x7FCC))

    a.label('save_context')
    for i,address in enumerate(CONTEXT_REGS): a.movff(address,b+0xD0+i)
    ret()
    a.label('restore_context')
    for i,address in reversed(list(enumerate(CONTEXT_REGS))):
        a.movff(b+0xD0+i,address)
    ret()
    data=bytearray(a.finish())
    for off,name in call_fixups:
        data[off:off+4]=absolute(0xEC00,a.labels[name])
    if a.pc>profile['code_limit']: raise ValueError('hooks exceed code limit')
    hooks=[]
    for address,preimage,name,kind,cont in HOOKS:
        hooks.append({'address':address,'expected_hex':preimage,
                      'new_hex':absolute(0xEC00 if kind=='CALL' else 0xEF00,a.labels[name]).hex(),
                      'role':'olympus_'+name,'continuation':cont,
                      'evidence':'O/keyboard_contract.json; O/hook_contract.json',
                      'wrapper_entry':a.labels[name]})
    # Every other original code/data byte remains protected, including native
    # camera, UART and radio scheduling. Shared HSS audit adds semantic closure.
    cursor=0x4002;protected=[]
    for address,*_ in HOOKS:
        protected.append({'start':cursor,'end':address,
                          'label':'O original code/data outside checked UI hooks'})
        cursor=address+4
    protected.append({'start':cursor,'end':0xABF0,
                      'label':'O original code/data outside checked UI hooks'})
    return {'sections':[{'address':code_base,'data':bytes(data),'role':'olympus_native_hooks'}],
            'hooks':hooks,'exports':{k:a.labels[k] for k in ('startup','service','lcd','press','power','idle','idle_deadline')},
            'labels':dict(a.labels), 'required_imports':list(needed),
            'unresolved_imports':unresolved,'protected_ranges':protected,
            'reserved_ram':[{'start':b+0xD0,'end':b+0xD0+len(CONTEXT_REGS),
                             'owner':'olympus_outer_native_context'}],
            'metadata':{'context_registers':list(CONTEXT_REGS),
                        'context_bytes':len(CONTEXT_REGS),
                        'native_key_history_mutation':False,
                        'secondary_flags_or':0x30,
                        'native_display_compare_precedes_transmit':True,
                        'irq_uses_separate_rx_ring':True,
                        'mode_key_native_path_preserved':True,
                        'ttl_def_air1_uses_original_ad_deadline':True,
                        'hardware_accessed':False}}
