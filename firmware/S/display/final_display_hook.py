#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Reapply canonical icons before native LCD change detection, Sony A6.

52DE is after original icon writers, before memcmp(49,2A7,11) and the
cooperative9E80 LCD serializer. This hook never replaces the serializer.
"""
import importlib.util
from pathlib import Path

_spec=importlib.util.spec_from_file_location('sony_final_display_asm',Path(__file__).with_name('display_adapter.py'))
_asm=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_asm)
Asm,absolute=_asm.Asm,_asm.absolute


def construct(original,base,*,state_base,redraw_icons,context_enter,context_leave):
    for address in (base,redraw_icons,context_enter,context_leave):
        if address&1 or not 0xAF80<=address<0xF800:
            raise ValueError('explicit extension addresses required')
    if not 0x464<=state_base or state_base+0x180>0xF00:
        raise ValueError('explicit state allocation candidate required')
    old=original[0x52DE-0x4000:0x52E2-0x4000]
    if old.hex()!='490e6b6f':raise ValueError('Sony final UI preimage mismatch')
    a=Asm(base)
    a.label('before_lcd_compare')
    # The preservation helpers are called also on fallback, so guard itself
    # cannot change the original native STATUS/BSR/other live context.
    a.call(context_enter)
    a.movff(state_base,0xFE8);a.w(0x0AA8)
    a.goto('restore_native','NZ')
    a.movff(0xDD,0xFE8);a.w(0x0900)
    a.goto('restore_native','NZ')
    a.call(redraw_icons)
    a.label('restore_native')
    a.call(context_leave)
    a.w(0x0E49,0x6F6B) # Exact displaced instructions, original BSR restored.
    a.goto(0x52E2)
    code=a.finish()
    if base+len(code)>0xF800:raise ValueError('hook exceeds code limit')
    return {'sections':[{'address':base,'data':code,'role':'sony_final_lcd_icons'}],
            'hooks':[{'address':0x52DE,'expected_hex':old.hex(),'new_hex':absolute(0xEF00,base).hex(),
                      'continuation':0x52E2,'role':'icons_before_native_lcd_compare',
                      'evidence':'51DE snapshots49..53 at entry, original52F0 compares then52FE callsAEB2 when changed;5318 calls9E80'}],
            'exports':a.labels,'imports':{'redraw_icons':redraw_icons,'context_enter':context_enter,'context_leave':context_leave},
            'state_base':state_base,'guards':{'runtime_magic':0xA8,'normal_ui_DD':0},
            'context_contract':'Parent helpers must preserve original caller live scratch/registers; LCD49..53 and native dirtyE3 must not be restored away.',
            'dirty_contract':'This hook relies on original subsequent memcmp. Core redraw occurring after51DE must separately set E3 viaAEB2.',
            'complete_firmware':False}
