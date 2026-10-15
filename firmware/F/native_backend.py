#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Fujifilm A5 native AIR2 bridge primitives. Offline source, not an installer.

The shared core owns policy; this module only uses F A5 native addresses.
The separate native_hooks module owns patch sites. Target proof fields enable
admission; the shared persistence component supplies actual NV operations.
Every generated primitive can be replayed with original native code in the VM.
"""
from pathlib import Path
import importlib.util
import hashlib

_spec = importlib.util.spec_from_file_location(
    'f_a5_assembler', Path(__file__).resolve().parent.parent / 'shared/runtime_generator.py')
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class Asm(_mod.Asm):
    """Keep this adapter's fixed-width branch API on the shared assembler."""
    @property
    def code(self):
        return bytes(self.data)

    def jump(self, label, kind='GOTO'):
        if kind == 'CALL':
            self.call(label)
        elif kind == 'GOTO':
            self.goto(label)
        else:
            raise ValueError('unsupported F branch kind: ' + kind)

    def finish(self):
        self.data = bytearray(self.finalize())

SOURCE_SHA256 = '403b13737bb8c6874d320266319ade0c6bae16aed91f79a41330a181b9355d91'
KEYS = (0x10a, 0x10e, 0x112, 0x116, 0x11a, 0x11e,
        0x122, 0x126, 0x12a, 0x12e, 0x132, 0x136)
SECONDARY = {0x11e: 1, 0x122: 2, 0x126: 4}
NATIVE = dict(signed_tenths=0x7ad2, sign=0x6e7e,
              blank=0xafe4, head_off=0xafd4, enqueue=0xa60a,
              queue_capacity=0x9562)


def construct_primitives(original, *, code_base, state_base, enable_admission=False,
                         core_imports=None, enable_nv_ready=False):
    """Generate offline primitives, with no flashable claim or inferred proof.

    `state_base` is a test/allocation parameter, NEVER a proof of available RAM.
    Native caller must save its live context before invoking these primitives.
    """
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError('F A5 stock image mismatch')
    if not (0xb2e0 <= code_base < 0x1f000 and code_base % 2 == 0):
        raise ValueError('unsupported code placement')
    if not (0 <= state_base <= 0xd80):
        raise ValueError('state block would exceed addressable GPR space')
    a = Asm(code_base)
    core_imports = dict(core_imports or {})
    S = lambda off: state_base + off
    def lit(v): a.w(0x0e00 | (v & 255))
    def mw(f): a.movff(0xfe8, f)
    def mf(f): a.movff(f, 0xfe8); a.w(0x0900)
    def setv(f, v): lit(v); mw(f)
    def ret(v=None): a.w(0x0012 if v is None else 0x0c00 | v)
    def go(label, cond=None):
        if cond: a.w({'BZ':0xe102, 'BNZ':0xe002, 'BC':0xe302, 'BNC':0xe202}[cond])
        a.jump(label, 'GOTO')
    def call(label): a.jump(label, 'CALL')
    def eq(f, val, reject): mf(f); a.w(0x0a00 | val); go(reject, 'BNZ')
    def bank0(): a.w(0x0100)

    # Snapshot remains valid even while editing is inhibited. Admission remains
    # opt-in until the separate interrupt CFG evidence is accepted by integration.
    a.label('read_inputs')
    for off in range(0x70, 0x80): setv(S(off), 0)
    eq(0x22, 0x8c, 'snapshot_bad'); eq(0x23, 1, 'snapshot_bad')
    mf(0x18c); a.w(0x0bfe); go('snapshot_bad', 'BNZ')
    a.movff(0x18c, S(0x70)); a.movff(0x60, S(0x71))
    for src, dst in ((0x29, 0x72), (0x38, 0x73)):
        mf(src); a.w(0x0b07); mw(S(dst))
    for src, dst in ((0x190,0x74),(0x191,0x75),(0x192,0x76),
                     (0x106,0x78),(0x107,0x79)):
        a.movff(src, S(dst))
    # Object byte0 bit0 is the most recent native scan sample, not a second
    # guessed GPIO polarity or a duplicate debounce engine.
    for key, mask in SECONDARY.items():
        mf(key); a.w(0x0b01); go('raw_%x_done' % key, 'BZ')
        mf(S(0x7a)); a.w(0x0900 | mask); mw(S(0x7a))
        a.label('raw_%x_done' % key)
    for key in KEYS:
        if key in SECONDARY: continue
        mf(key); a.w(0x0b01); go('other_key_down', 'BNZ')
    go('snapshot_good')
    a.label('other_key_down'); setv(S(0x7b), 1)
    a.label('snapshot_good'); setv(S(0x77), 0x80)
    if enable_admission:
        call('native_idle'); a.w(0x0900); go('snapshot_return', 'BZ')
        setv(S(0x77), 0x83)
        if enable_nv_ready:
            mf(S(0x7a));go('snapshot_return','BNZ')
            mf(S(0x7b));go('snapshot_return','BNZ')
            setv(S(0x77),0x87)
    a.label('snapshot_return'); ret(1)
    a.label('snapshot_bad'); ret(0)

    # No flash/camera IRQ is disabled. Original ISR only produces RX ring01A5;
    # TX ring0092 has foreground producers (see independent CFG audit). These
    # checks are conservative queue admission, not a promise about future IRQs.
    a.label('native_idle')
    for address in (0x7a, 0x28, 0x61, 0x85, 0x94):
        eq(address, 0, 'native_busy')
    eq(0x3a, 1, 'native_busy')
    mf(0xfa4); a.w(0x0b80); go('native_busy', 'BNZ')
    mf(0xff0); a.w(0x0b06); go('native_busy', 'BNZ')
    ret(1)
    a.label('native_busy'); ret(0)

    # Raw enqueue is a replay/test primitive, intentionally not the ABI tx_frame.
    # ABI tx_frame remains fail-closed until concurrent producers are audited.
    a.label('enqueue_preflight')
    bank0(); lit(17); a.call(NATIVE['queue_capacity']); a.w(0x0900)
    go('enqueue_refused', 'BZ')
    for off in range(16): a.movff(S(0x30+off), 0xc0+off)
    setv(0xbb, 0xc0); bank0(); a.call(NATIVE['enqueue']); ret()
    a.label('enqueue_refused'); ret(0)
    a.label('tx_frame')
    if enable_admission:
        call('native_idle'); a.w(0x0900); go('enqueue_refused', 'BZ')
        go('enqueue_preflight')
    else: ret(0)

    # Native signed formatter supports <=99 tenths and the 100 endpoint.
    # W=kind 0 blank /1 signed /2 absolute /3 head off; provider+17C=row1..3.
    # +61=value. No writes to RF, mode/config or canonical core state.
    a.label('render_row')
    mw(S(0x17d)); bank0()
    for row, dest in ((1,0x88),(2,0x8a),(3,0x8c)):
        mf(S(0x17c)); a.w(0x0a00 | row); go('row_%d' % row, 'BZ')
    ret(0)
    for row, dest in ((1,0x88),(2,0x8a),(3,0x8c)):
        a.label('row_%d' % row); setv(S(0x17e), dest); go('render_selected')
    a.label('render_selected')
    mf(S(0x17d)); go('render_blank', 'BZ')
    a.w(0x0a03); go('render_off', 'BZ')
    setv(0xb4,0x87); a.movff(S(0x17e),0xb5); a.movff(S(0x61),0xb6)
    bank0(); a.call(NATIVE['signed_tenths'])
    mf(S(0x17d)); a.w(0x0a02); go('render_success','BNZ')
    setv(0xb0,0x87); a.movff(S(0x17e),0xb1); setv(0xb2,2)
    bank0(); a.call(NATIVE['sign']); go('render_success')
    a.label('render_blank'); setv(0xb7,0x87); a.movff(S(0x17e),0xb8)
    bank0(); a.call(NATIVE['blank']); go('render_success')
    a.label('render_off'); setv(0xb7,0x87); a.movff(S(0x17e),0xb8)
    bank0(); a.call(NATIVE['head_off'])
    a.label('render_success'); ret(1)

    # Native camera/TTL state remains ABC even while the visible page is DEF.
    # 6492 only updates selection and callback pointers; it does not enqueue RF.
    a.label('apply_native_state')
    mw(S(0x17b)); call('native_idle'); a.w(0x0900); go('apply_refused','BZ')
    eq(0x22,0x8c,'apply_refused'); eq(0x23,1,'apply_refused')
    # Snapshot/native global mode must still agree before any mutation. This
    # allows restored startup mode to differ from core[1] without overwriting
    # a newer camera-origin mode event observed after the captured snapshot.
    a.movff(S(0x70),0xb0);mf(0x18c);bank0();a.w(0x19b0);go('apply_refused','BNZ')
    mf(S(1)); a.w(0x0bfe); go('apply_refused','BNZ')
    for selected in (1,2,3,7):
        mf(S(4));a.w(0x0a00|selected);go('apply_fields_valid','BZ')
    go('apply_refused')
    a.label('apply_fields_valid')
    mf(S(0x17b)); a.w(0x0b01); go('apply_no_mode','BZ')
    a.movff(S(1),0x18c); setv(0x61,0)
    bank0(); lit(0); a.call(0xb024)
    setv(0xc3,0); setv(0xc4,0); bank0(); a.call(0xa786); a.call(0x5f64)
    a.label('apply_no_mode')
    mf(S(0x17b)); a.w(0x0b02); go('apply_no_fec','BZ')
    for src,dest in ((0x14,0x190),(0x15,0x191),(0x16,0x192)):
        a.movff(S(src),dest)
    a.label('apply_no_fec')
    mf(S(0x17b)); a.w(0x0b05); go('apply_no_select','BZ')
    mf(S(4)); bank0(); a.call(0x6492)
    a.label('apply_no_select')
    mf(S(0x17b)); a.w(0x0b08); go('apply_success','BZ')
    mf(S(5)); a.w(0x0b07); mw(0x29)
    mf(S(6)); a.w(0x0b07); mw(0x38)
    a.label('apply_success'); ret(1)
    a.label('apply_refused'); ret(0)

    # Final LCD flush still belongs to the native UI loop. No hardware writes.
    a.label('redraw')
    if core_imports.get('display_row'):
        # Avoid calling 9C74/742E: the eventual 742E hook invokes this backend.
        # Keep original mode/sync/channel/selection glyph helpers, then project
        # page-local icons directly to LCD RAM (never to native camera masks).
        bank0()
        for addr in (0x80ec,0x880e,0x7d88,0x8154): a.call(addr)
        # F's stock 880E selection helper handles only rows 1/2/3; its selector
        # 7 clears all boxes. AIR2 ALL means every visible row. These are the
        # union of F's own three native box bits, not Canon's LCD layout.
        mf(S(4)); a.w(0x0a07); go('redraw_selection_done','BNZ')
        mf(0x87); a.w(0x092a); mw(0x87)
        a.label('redraw_selection_done')
        for row in (1,2,3):
            setv(S(0x17c),row); lit(row); a.call(core_imports['display_row'])
            call('render_row')
        mf(S(3)); go('redraw_abc_labels','BZ')
        mf(0x87); a.w(0x0bea); mw(0x87); go('redraw_model')
        a.label('redraw_abc_labels'); mf(0x87); a.w(0x0915); mw(0x87)
        a.label('redraw_model')
        a.movff(S(5),S(0x179)); mf(S(6)); a.movff(S(0x179),0xb0)
        bank0(); a.w(0x15b0); mw(S(0x179))
        mf(S(3)); go('redraw_model_ready','BZ')
        mf(S(0x179)); a.w(0x42e8); a.w(0x42e8); a.w(0x42e8); mw(S(0x179))
        a.label('redraw_model_ready')
        for bit,lcd_bit in ((0,4),(1,6),(2,7)):
            mf(S(0x179)); a.w(0x0b00|(1<<bit)); go('model_on_%d'%bit,'BNZ')
            bank0(); a.w(0x9100|(lcd_bit<<9)|0x8e); go('model_done_%d'%bit)
            a.label('model_on_%d'%bit); bank0(); a.w(0x8100|(lcd_bit<<9)|0x8e)
            a.label('model_done_%d'%bit)
        # Show A/b/C or d/E/F when the page actually changes. A later redraw
        # restores the values, matching P8's action-bound hint (no new timer).
        # FF marks the first render after reset and suppresses a boot hint.
        mf(S(3)); a.movff(0xfe8,0xb0); mf(S(0x17f)); bank0(); a.w(0x19b0)
        go('redraw_done','BZ')
        mf(S(0x17f)); a.w(0x0aff); go('redraw_first','BZ')
        a.movff(S(3),S(0x17f))
        for row,dest in ((1,0x88),(2,0x8a),(3,0x8c)):
            setv(0xb7,0x87);setv(0xb8,dest);bank0();a.call(0xafe4)
            mf(S(3));go('hint_abc_%d'%row,'BZ')
            setv(0xb2,12+row);go('hint_write_%d'%row)
            a.label('hint_abc_%d'%row);setv(0xb2,9+row)
            a.label('hint_write_%d'%row);setv(0xb1,dest);bank0();a.call(0xa6ba)
            mf(dest);a.w(0x0b7f);mw(dest)
        go('redraw_done')
        a.label('redraw_first');a.movff(S(3),S(0x17f))
        a.label('redraw_done')
        ret(1)
    else:
        ret(0)

    # Native ISR AE22 writes camera command to RAM0FE.  Never restore that byte
    # from a foreground snapshot.  Also never restore ISR-owned2B1/1DA/1E0.
    # This pair is not reentrant; only outer foreground hooks may invoke it.
    context = [0xfe8,0xfd8,0xfe0,0xfe9,0xfea,0xfe1,0xfe2,0xfd9,0xfda,
               0xff3,0xff4,0xff5,0xff6,0xff7,0xff8,0xffa,0xffb]
    context += [f for f in range(0xb0,0x100) if f != 0xfe]
    context += list(range(0x2c0,0x300))
    assert len(context) <= 0xc0
    a.label('context_save')
    for i, f in enumerate(context): a.movff(f,S(0xb0+i))
    ret()
    a.label('context_restore')
    for i, f in reversed(list(enumerate(context))): a.movff(S(0xb0+i),f)
    ret()

    # The shared linker replaces these two import addresses with the qualified
    # persistence component. Standalone primitive builds explicitly refuse NV.
    for name in ('nv_load', 'nv_commit'):
        a.label(name); ret(0)
    a.finish()
    return dict(sections=[dict(address=code_base, data=a.code, role='F_A5_native_primitives')],
                hooks=[], exports=a.labels,
                required_imports=['display_row'],
                unresolved_imports=[] if core_imports.get('display_row') else ['display_row'],
                metadata=dict(status='OFFLINE_BACKEND_REPLAYED_NOT_HARDWARE_VALIDATED',
                              readiness_bits=(7 if enable_nv_ready else 3) if enable_admission else 0, nv_enabled=False,
                              core_state_preserved=True, original_HSS_modified=False,
                              context_saved_addresses=context,
                              context_excludes_ISR_owned=[0xfe,0x2b1,0x1da,0x1e0],
                              state_base=state_base, state_span=0x180,
                              qualification=dict(ram_allocation='external shared audit required',
                                  native_admission_enabled=bool(enable_admission),
                                  nv_readiness_enabled=bool(enable_nv_ready),
                                  complete_hooks='separate native_hooks.py; integrated replay required',
                                  nv_storage='external shared persistence exports required',
                                  physical_validation=False)))


def construct(original, *, app_base=0x4000, code_base, profile, imports=None):
    """Shared-builder API; full hook closure and NV qualification stay separate."""
    if app_base != 0x4000 or profile.get('model_tag') != 'F':
        raise ValueError('F A5 profile/base mismatch')
    result = construct_primitives(original, code_base=code_base,
        state_base=profile['state_base'],
        enable_admission=bool(profile.get('native_admission_proven',False)),
        core_imports=imports,
        enable_nv_ready=bool(profile.get('native_nv_gate_proven',
                                         profile.get('nvm_admission_proven',False))))
    result['reserved_ram']=[dict(start=profile['state_base'],end=profile['state_base']+0x180,
                                owner='shared_core_and_F_native_provider')]
    return result
