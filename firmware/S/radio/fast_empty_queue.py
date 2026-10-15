#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Sony-only short empty-queue commit candidate. No hook or image output.

Foreground-only: the hook must not run inside 5C08/5DA4 or an ISR. The selected
camera predicates identify known inactive software states, not measured RF/HSS
completion. A post-commit original abort remains authoritative.
"""
import pic18_emit as asm


def construct(base, frame_ram, irq_ram):
    if base & 1 or base < 0xAF80:
        raise ValueError('aligned code placement outside original code required')
    occupied = set(range(frame_ram, frame_ram+16)) | {irq_ram}
    if frame_ram < 0x100 or frame_ram+16 > 0xF00 or not 0x100 <= irq_ram < 0xF00:
        raise ValueError('caller-owned RAM must be above bank0 and below SFRs')
    if len(occupied) != 17 or occupied & set(range(0x400,0x464)):
        raise ValueError('frame/control RAM overlaps each other or native queue')
    a = asm.Asm(base)

    def movf(address):
        a.w(0x0100 | (address>>8), 'MOVLB explicit bank')
        a.w(0x5100 | (address&255), 'MOVF %03X,W,BANKED'%address)

    def equal(address, value, fail):
        movf(address)
        if value: a.w(0x0A00|value,'XORLW required value')
        a.jump(fail,'BNZ')

    def quiet(fail, suffix):
        # These are observed software stages, never a blanket RF-idle claim.
        equal(0x0D8,0,fail)
        equal(0x0E8,0,fail)
        equal(0x056,1,fail)
        equal(0x048,0,fail)
        movf(0x194)
        a.jump('camera_ok_'+suffix,'BZ')
        a.w(0x0A05,'XORLW terminal camera state 5')
        a.jump(fail,'BNZ')
        a.label('camera_ok_'+suffix)
        # Pending original camera event bits: no flag is acknowledged here.
        for sfr, bit in ((0xFF0,0),(0xFF0,1),(0xF98,4),(0xFA4,7)):
            a.w(0xB000 | (bit<<9) | (sfr&255),'BTFSC pending camera IRQ')
            a.jump(fail)

    a.label('sony_air2_fast_try_queue')
    a.w(0xB258,'BTFSC RAM58 ISR active bit1')
    a.jump('refuse_unmasked')
    quiet('refuse_unmasked','pre')
    # Fixed descriptor contract must remain the original E6/0400/100 layout.
    equal(0xE9,100,'refuse_unmasked')
    equal(0xEA,0,'refuse_unmasked')
    equal(0xEB,4,'refuse_unmasked')
    a.movff(0xFF2,irq_ram)
    a.w(0x0100|(irq_ram>>8),'MOVLB irq-state bank')
    a.w(0x9100|(irq_ram&255),'BCF own saved bit0; accepted flag')
    a.label('mask_begin')
    a.w(0x9EF2,'BCF INTCON.GIEH')
    a.w(0x9CF2,'BCF INTCON.GIEL')
    a.label('masked_recheck')
    quiet('restore','locked')
    a.label('commit_begin')
    a.w(0x0104,'MOVLB 4')
    a.w(0x6B00,'CLRF 400; native normal-frame marker')
    for i in range(16):
        a.movff(frame_ram+i,0x401+i)
    a.w(0x0100,'MOVLB 0')
    a.w(0x6BE7,'CLRF read index')
    a.w(0x0E11,'MOVLW 17')
    a.w(0x6FE6,'MOVWF write index')
    a.label('publish')
    a.w(0x6FE8,'MOVWF count; linearization point')
    a.w(0x0100|(irq_ram>>8),'MOVLB own state')
    a.w(0x8100|(irq_ram&255),'BSF own bit0; accepted')
    a.label('restore')
    a.w(0x0100|(irq_ram>>8),'MOVLB saved state bank')
    a.w(0xBD00|(irq_ram&255),'BTFSC saved GIEL bit6')
    a.w(0x8CF2,'BSF INTCON.GIEL; preserve every other live bit')
    a.w(0xBF00|(irq_ram&255),'BTFSC saved GIEH bit7')
    a.label('restore_high')
    a.w(0x8EF2,'BSF INTCON.GIEH; preserve pending flags')
    a.label('mask_end')
    a.w(0x0100|(irq_ram>>8),'MOVLB own state bank')
    a.w(0xB100|(irq_ram&255),'BTFSC accepted bit0')
    a.w(0x0C01,'RETLW locally accepted, not RF ACK')
    a.label('refuse_unmasked')
    a.w(0x0C00,'RETLW not submitted')
    # Read-only snapshot for the shared backend. Appended so the transaction
    # entry and its critical region retain exactly their previous layout.
    a.label('sony_air2_quiet')
    a.w(0xB258,'BTFSC RAM58 ISR active bit1')
    a.jump('quiet_refuse')
    quiet('quiet_refuse','probe')
    equal(0xE9,100,'quiet_refuse')
    equal(0xEA,0,'quiet_refuse')
    equal(0xEB,4,'quiet_refuse')
    a.w(0x0C01,'RETLW observed software quiet; not physical HSS guarantee')
    a.label('quiet_refuse')
    a.w(0x0C00,'RETLW not quiet')
    code=a.finalize()
    return code, {'labels':a.labels,'base':base,'end':a.pc,'frame_ram':frame_ram,
                  'irq_ram':irq_ram,'clobbers':['W','STATUS','BSR','caller irq_ram'],
                  'ready_predicate':{'D8':0,'E8':0,'56':1,'48':0,'194':[0,5],
                      'pending_zero':['FF0.0','FF0.1','F98.4','FA4.7']},
                  'linearization':'write E8=17 after all 17 bytes and both indices',
                  'quiet_export':'W1/0 read-only snapshot; does not mask IRQ or establish future physical idle',
                  'excludes':['consumer reentrancy','ISR callsites'],
                  'not_proven':['physical HSS idle','oscillator frequency','wire timing'],
                  'interrupt_policy':'save GIEH/GIEL; bitwise restore; never alter IPEN/IF'}
