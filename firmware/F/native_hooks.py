#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""F A5 foreground AIR2 hooks; pure generation, no image/updater output."""
from native_backend import Asm, SOURCE_SHA256
import hashlib


def construct(original, *, app_base=0x4000, code_base, profile, core, backend):
    core=core.get('exports',core);backend=backend.get('exports',backend)
    if app_base != 0x4000 or hashlib.sha256(original).hexdigest()!=SOURCE_SHA256:
        raise ValueError('F A5 stock mismatch')
    if profile.get('model_tag')!='F' or not profile.get('ram_proven'):
        raise ValueError('F RAM profile proof required for native hooks')
    for name in ('init','service','power_edit','select_row','secondary_press','idle_expired'):
        if not core.get(name):raise ValueError('missing core export '+name)
    for name in ('context_save','context_restore','redraw'):
        if not backend.get(name):raise ValueError('missing F native export '+name)
    state=profile['state_base'];a=Asm(code_base)
    def lit(v):a.w(0x0e00|(v&255))
    def mf(f):a.movff(f,0xfe8);a.w(0x0900)
    def ret():a.w(0x0012)
    def go(n,cond=None):
        if cond:a.w({'BZ':0xe102,'BNZ':0xe002}[cond])
        a.jump(n,'GOTO')
    def save():a.call(backend['context_save'])
    def restore():a.call(backend['context_restore'])
    def guard(fallback):mf(state);a.w(0x0aa8);go(fallback,'BNZ')
    a.label('cold_clear')
    lit(0);a.movff(0xfe8,state);lit(255);a.movff(0xfe8,state+0x17f);a.goto(0x4c3a)
    a.label('init_hook');a.call(0x932c);save();a.call(core['init']);restore();ret()
    a.label('service_hook');a.call(0xa50e);save();guard('service_return')
    a.call(core['service']);a.label('service_return');restore();ret()

    a.label('normal_press_hook');save();guard('press_original')
    mf(0xeb);a.w(0x0a01);go('press_original','BNZ')
    for key,name,arg in ((0x16,'select_row',1),(0x1a,'select_row',2),
                         (0x1e,'secondary_press',1),(0x22,'secondary_press',2),
                         (0x26,'secondary_press',4)):
        mf(0xea);a.w(0x0a00|key);go('press_%x'%key,'BZ')
    go('press_original')
    for key,name,arg in ((0x16,'select_row',1),(0x1a,'select_row',2),
                         (0x1e,'secondary_press',1),(0x22,'secondary_press',2),
                         (0x26,'secondary_press',4)):
        a.label('press_%x'%key);lit(arg);a.call(core[name]);restore();ret()
    a.label('press_original');restore();lit(0x0a);a.w(0x0100);a.goto(0x5e6e)

    a.label('power_hook');save();guard('power_original')
    # context_save puts original W at provider offset B0.
    a.movff(state+0xb0,0xfe8);a.call(core['power_edit']);restore();ret()
    a.label('power_original');restore();a.w(0x6fe2);a.call(0x569a);a.goto(0x8d84)

    a.label('display_hook');save();guard('display_original')
    a.call(backend['redraw']);restore();ret()
    a.label('display_original');restore();a.call(0x569a);a.goto(0x7432)

    # Native 8618..8622 admits only MAN to the A6 idle deadline check.
    # Extend that gate solely for TTL's DEF AIR1 page. Preserve the original
    # indirect-mode read/flags/FSR2 effects before either native continuation.
    # The original 8FBE/78E0 expiry check and B13A deadline reset stay in place.
    a.label('idle_gate_hook');save();guard('idle_gate_original')
    for address,value in ((0x22,0x8c),(0x23,1),(0x18c,0),
                          (state+1,0),(state+2,1),(state+3,1)):
        mf(address);a.w(0x0a00|value);go('idle_gate_original','BNZ')
    restore();a.movff(0x22,0xfd9);a.movff(0x23,0xfda);a.w(0x04de)
    a.goto(0x8624)
    a.label('idle_gate_original');restore()
    a.movff(0x22,0xfd9);a.movff(0x23,0xfda);a.w(0x04de)
    a.w(0xe002);a.goto(0x8644);a.goto(0x8624)

    # GOTO splice, not CALL: a deferred AIR1 clear must skip native B13A's
    # deadline reset. Native 78E0 has latched A6=FFFF on expiry; retain that
    # latch so the next idle pass retries instead of disarming A6 with zero.
    # AIR2 remains resident and consumes its ordinary native expiry normally.
    a.label('idle_hook');save();guard('idle_original')
    mf(state+2);a.w(0x0a01);go('idle_nonrelative','BNZ')
    a.call(core['idle_expired']);a.w(0x0900);go('idle_deferred','BZ')
    go('idle_done')
    a.label('idle_nonrelative');a.call(core['idle_expired'])
    a.label('idle_done');restore();a.goto(0x863a)
    a.label('idle_deferred');restore();a.goto(0x8644)
    a.label('idle_original');restore();a.call(0x742e);a.goto(0x863a)
    a.finish()
    # Exact native instruction boundaries; 8D7E spans MOVWF + CALL = six bytes.
    sites=[(0x6068,4,'cold_clear','GOTO',0x4c3a,'startup after original RAM initialization'),
           (0x4d7e,4,'init_hook','CALL',0x4d82,'original camera constructor then core init'),
           (0x5a2c,4,'service_hook','CALL',0x5a30,'original object service then cooperative core service'),
           (0x5e6a,4,'normal_press_hook','GOTO',0x5e6e,'normal UI only; preserve original activity prefix in8700'),
           (0x8d7e,6,'power_hook','GOTO',0x8d84,'short and held power shared endpoint; never duplicate native RF'),
           (0x742e,4,'display_hook','GOTO',0x7432,'canonical values, native fixed LCD helpers'),
           (0x8618,4,'idle_gate_hook','GOTO',0x861c,'preserve native MAN gate and add TTL DEF AIR1 to the original A6 expiry path'),
           (0x8636,4,'idle_hook','GOTO',0x863a,'original A6 expiry; preserve deadline while AIR1 clear is deferred by a pending transaction')]
    hooks=[]
    for address,length,name,kind,continuation,evidence in sites:
        b=Asm(address)
        (b.call if kind=='CALL' else b.goto)(a.labels[name])
        while len(b.code)<length:b.w(0)
        expected=original[address-app_base:address-app_base+length]
        hooks.append(dict(address=address,expected_hex=expected.hex(),new_hex=b.code.hex(),
                          role='F_A5_UI_hook',continuation=continuation,evidence=evidence))
    return dict(sections=[dict(address=code_base,data=a.code,role='F_A5_native_hooks')],
                hooks=hooks,exports=a.labels,required_imports=[],unresolved_imports=[],
                metadata=dict(status='OFFLINE_HOOKS_REQUIRE_INTEGRATED_REPLAY',
                              original_HSS_modified=False,context_preserves_ISR_FE=True,
                              magic=0xa8,hook_count=len(hooks)))
