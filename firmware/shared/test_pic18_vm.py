#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Offline checks: instruction semantics plus original N/S/F/O helper bytes.

No USB, updater, firmware construction or file writes. Prints a JSON report.
Assertions are explicit exceptions so python -O runs the same checks.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
from pic18_vm import CPU, VMError, UnknownCode, UnsupportedInstruction, PeripheralBoundary, StepLimit

HERE = Path(__file__).resolve().parent
COUNTS = {}
STOCK_SHA = {
    'N': 'd8a58e3bbaeee752b31e698c287c474b4ab027fb29939720e1441a39cb3f0aba',
    'S': 'abed888029102baea3a3f003ee40d8ab27119a3b1c3ff988342dbfaf8437984b',
    'F': '403b13737bb8c6874d320266319ade0c6bae16aed91f79a41330a181b9355d91',
    'O': '84645f098eeab93dd41d150015c7c642207037b7605b937b0a13388df1805976',
}
MASK_SHA = '81fe4da4f8a15728c97bc6de35fae71572d44f39a927dce22a9ca300b5d2558b'


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def passed(name, count=1):
    COUNTS[name] = COUNTS.get(name, 0) + count


def words(*values):
    return b''.join(v.to_bytes(2, 'little') for v in values)


def program(*values, **kwargs):
    return CPU(words(*values), base=0, **kwargs)


def must_raise(cls, action, label):
    try:
        action()
    except cls:
        passed('fail_closed')
        return
    raise AssertionError('did not reject ' + label)


def signed8(x):
    return x if x < 128 else x - 256


def expected_flags(result, carry, dc, signed_result):
    return int(carry) | int(dc) << 1 | int(result == 0) << 2 | int(not -128 <= signed_result <= 127) << 3 | (result & 128) >> 3


def arithmetic_tests():
    # Use the real decoder and instruction runner, not the CPU private ALU APIs.
    for opname, opcode in (('ADDWFC', 0x2220), ('SUBWFB', 0x5A20), ('SUBFWB', 0x5620)):
        cpu = program(opcode, 0x0012)
        for f in range(256):
            for w in range(256):
                for carry in (0, 1):
                    cpu.m[0x20] = f
                    cpu.w = w
                    cpu.m[0xFD8] = 0x1F if carry else 0x1E
                    cpu.run(0)
                    if opname == 'ADDWFC':
                        total = f + w + carry
                        dc = (f % 16 + w % 16 + carry) >= 16
                        ovtotal = signed8(f) + signed8(w) + carry
                        cf = total >= 256
                    else:
                        left, right = (w, f) if opname == 'SUBFWB' else (f, w)
                        total = left - right - (1 - carry)
                        dc = left % 16 - right % 16 - (1 - carry) >= 0
                        ovtotal = signed8(left) - signed8(right) - (1 - carry)
                        cf = total >= 0
                    result = total % 256
                    expected = expected_flags(result, cf, dc, ovtotal)
                    check(cpu.m[0x20] == result and cpu.m[0xFD8] == expected,
                          '%s f=%02X w=%02X c=%d' % (opname, f, w, carry))
                    passed('arithmetic_exhaustive')
    for op, delta in ((0x2A20, 1), (0x0620, -1)):
        cpu = program(op, 0x0012)
        for value in range(256):
            cpu.m[0x20] = value
            cpu.m[0xFD8] = 0
            cpu.run(0)
            total = value + delta
            flags = expected_flags(total & 255, total > 255 if delta > 0 else total >= 0,
                                   value % 16 + delta > 15 if delta > 0 else value % 16 + delta >= 0,
                                   signed8(value) + delta)
            check(cpu.m[0x20] == total & 255 and cpu.m[0xFD8] == flags, 'INC/DEC flags')
            passed('inc_dec_flags')
    # DAW is meaningful after adding two BCD operands; check all such additions.
    cpu = program(0x2420, 0x0007, 0x0012)
    for a in range(100):
        for b in range(100):
            cpu.w = (a // 10) * 16 + a % 10
            cpu.m[0x20] = (b // 10) * 16 + b % 10
            cpu.m[0xFD8] = 0
            cpu.run(0)
            decimal = (a + b) % 100
            check(cpu.w == (decimal // 10) * 16 + decimal % 10 and bool(cpu.m[0xFD8] & 1) == (a + b >= 100), 'BCD DAW')
            passed('daw_decimal_pairs')


def indirect_tests():
    sfrs = ((0xFE9, 0xFEA, 0xFEB), (0xFE1, 0xFE2, 0xFE3), (0xFD9, 0xFDA, 0xFDB))
    for i, (_, _, first) in enumerate(sfrs):
        for mode, offset in (('PREINC', 1), ('POSTDEC', 2), ('POSTINC', 3), ('INDF', 4), ('PLUSW', 0)):
            for pointer in (0x3FF, 0x400):
                alias = first + offset
                cpu = program(0x2A00 | (alias & 255), 0x0012)  # INCF alias,F,ACCESS
                cpu.set_fsr(i, pointer)
                cpu.w = 0xFE  # PLUSW: -2
                effective = pointer + (1 if mode == 'PREINC' else -2 if mode == 'PLUSW' else 0)
                cpu.m[effective] = 41
                cpu.m[(effective + 1) & 0xFFF] = 99
                cpu.run(0)
                final = pointer + (1 if mode in ('PREINC', 'POSTINC') else -1 if mode == 'POSTDEC' else 0)
                check(cpu.m[effective] == 42 and cpu.m[(effective + 1) & 0xFFF] == 99 and cpu.get_fsr(i) == final, 'indirect RMW advances once')
                passed('indirect_rmw')
        cpu = program(0x0000, 0x0012)
        for virtual in (0xFEF, 0xFDF, 0xFE3):
            cpu.set_fsr(i, virtual)
            check(cpu.read(first + 4) == 0, 'virtual indirect reads zero')
            cpu.write(first + 4, 91)
            check(cpu.get_fsr(i) == virtual, 'virtual indirect write ignored')
            passed('indirect_virtual')
    cpu = program(0xCFE6, 0xFFDE, 0x0012)  # MOVFF POSTINC1,POSTINC2
    cpu.set_fsr(1, 0x4FF)
    cpu.set_fsr(2, 0x600)
    cpu.m[0x4FF] = 0xAC
    cpu.run(0)
    check(cpu.m[0x600] == 0xAC and cpu.get_fsr(1) == 0x500 and cpu.get_fsr(2) == 0x601, 'MOVFF two independent operands')
    passed('movff_indirect')


def control_and_boundary_tests():
    for oldstatus in range(32):
        cpu = program(0x6AD8, 0x0012)  # CLRF STATUS affects only Z.
        cpu.m[0xFD8] = oldstatus
        cpu.run(0)
        check(cpu.m[0xFD8] == oldstatus | 4, 'STATUS result write inhibition')
        passed('status_destination')
    for literal in range(256):
        cpu = program(0x0100 | literal, 0x0012)
        cpu.run(0)
        check(cpu.m[0xFE0] == literal & 15, 'MOVLB ignores literal high nibble')
        passed('movlb_literal')
    # Skip the full four-byte GOTO; no execution of the skipped target.
    cpu = program(0xB020, 0xEFEE, 0xFFFF, 0x0E5A, 0x0012)
    cpu.run(0)
    check(cpu.w == 0x5A, 'skip long instruction')
    passed('control')
    # Native C18-style indirect dispatch via PUSH, MOVWF TOSL, RETURN.
    cpu = program(0x0005, 0x0E0C, 0x6EFD, 0x0012, 0xFFFF, 0xFFFF, 0x0E63, 0x0012)
    cpu.run(0)
    check(cpu.w == 99 and not cpu.stack, 'PUSH/TOS indirect return')
    passed('control')
    # ADDWF PCL,W reads pc+2; destination PCL uses latches and has no carry into them.
    cpu = program(0x0E04, 0x26F9, 0xFFFF, 0xFFFF, 0x0E4A, 0x0012)
    cpu.run(0)
    check(cpu.w == 0x4A, 'computed PCL branch')
    passed('control')
    cpu = program(0x0E22, 0xED05, 0xF000, 0x0012, 0xFFFF, 0x0E88, 0x0013)
    cpu.m[0xFD8] = 0x15
    cpu.m[0xFE0] = 7
    cpu.run(0)
    check((cpu.w, cpu.m[0xFD8], cpu.m[0xFE0]) == (0x22, 0x15, 7), 'fast shadow')
    passed('control')
    cpu = program(0x0009, 0x000B, 0x0012, 0x55AA, 0x9977)
    cpu.set_tblptr(6)
    cpu.run(0)
    check(cpu.m[0xFF5] == 0x77 and cpu.tblptr() == 8, 'TBLRD index')
    passed('table')
    cpu = program(0x000D, 0x0012)
    cpu.set_tblptr(0xF800)
    cpu.m[0xFF5] = 0xA5
    before = bytes(cpu.flash)
    cpu.run(0)
    check(cpu.latches == {0xF800: 0xA5} and bytes(cpu.flash) == before, 'table write is latch only')
    passed('table')
    for initial, opcode, expected, latch in ((0x3FFFFF, 0x000D, 0x200000, 0x3FFFFF),
                                             (0x200000, 0x000E, 0x3FFFFF, 0x200000),
                                             (0x1FFFFF, 0x000F, 0, 0)):
        cpu = program(opcode, 0x0012)
        cpu.set_tblptr(initial)
        cpu.m[0xFF5] = 0x59
        cpu.run(0)
        check(cpu.tblptr() == expected and cpu.latches == {latch: 0x59}, '22-bit TBLPTR preserves bit21')
        passed('table_upper_bit')
    must_raise(UnknownCode, lambda: CPU(words(0x0012), mask=b'\0\1', base=0).run(0), 'unknown byte')
    must_raise(UnsupportedInstruction, lambda: program(0xFFFF).run(0), 'erased code')
    must_raise(UnsupportedInstruction, lambda: program(0x0010).run(0), 'interrupt return')
    must_raise(UnsupportedInstruction, lambda: CPU(b'', xinst=True), 'XINST')
    must_raise(UnsupportedInstruction, lambda: program(0xC020, 0xFFFD).run(0), 'MOVFF to TOS')
    must_raise(PeripheralBoundary, lambda: program(0x50AD, 0x0012).run(0), 'unprovided UART state')
    must_raise(PeripheralBoundary, lambda: program(0x8EA6, 0x0012).run(0), 'unprovided flash controller')
    must_raise(StepLimit, lambda: program(0xD7FF).run(0, max_steps=7), 'infinite loop')
    cpu = program(0x50AD, 0x0012)
    cpu.read_hooks[0xFAD] = lambda c: 0x5A
    cpu.run(0)
    check(cpu.w == 0x5A and cpu.events == [('read_hook', 0, 0xFAD, 0x5A)], 'explicit MMIO evidence')
    passed('boundary_hook')


def stock(brand):
    p = HERE / 'stock' / brand
    image = (p / 'original.base4000.partial.bin').read_bytes()
    mask = (p / 'original.known_mask.bin').read_bytes()
    check(hashlib.sha256(image).hexdigest() == STOCK_SHA[brand], 'stock hash ' + brand)
    check(hashlib.sha256(mask).hexdigest() == MASK_SHA, 'mask hash ' + brand)
    return image, mask


def native_helpers():
    stocks = {brand: stock(brand) for brand in 'NSFO'}
    for brand, entry, param, obj in (('N', 0x8E62, 0x0D, 0x272), ('S', 0x930E, 0x6B, 0x125), ('F', 0x97C0, 0xB0, 0x700)):
        image, mask = stocks[brand]
        cpu = CPU(image, mask=mask)
        for old in range(256):
            for pressed in (0, 1, 2, 255):
                cpu.m[0xFE0] = 0
                cpu.m[param:param+3] = bytes((obj & 255, obj >> 8, pressed))
                cpu.m[obj:obj+4] = bytes((old, 0x12, 0x34, 0x56))
                cpu.run(entry)
                expected = (old & 128) | (((old << 1) | int(pressed == 1)) & 127)
                check(bytes(cpu.m[obj:obj+4]) == bytes((expected, 0x12, 0x34, 0x56)), brand + ' key history')
                check(not cpu.events, 'native pure helper has no external replacements')
                passed(brand + '_native_key_history')
    for brand, entry, end in (('N', 0xA2EA, 101), ('F', 0xAA2C, 100)):
        image, mask = stocks[brand]
        cpu = CPU(image, mask=mask)
        for n in range(end):
            cpu.w = n
            cpu.run(entry)
            check(cpu.w == (n // 10) * 16 + n % 10, brand + ' BCD')
            passed(brand + '_native_bcd')
    image, mask = stocks['S']
    cpu = CPU(image, {0xD2: 0x93, 0xD3: 1}, mask=mask)
    for mode in (0, 1):
        cpu.m[0x193] = mode
        cpu.run(0x9690)
        check(cpu.w == mode and bool(cpu.m[0xFD8] & 4) == (mode == 0), 'Sony mode getter')
        passed('S_native_mode')
    image, mask = stocks['F']
    cpu = CPU(image, {0xB0: 0, 0xB1: 7, 0xB2: 0x63, 0xB3: 0x9D}, mask=mask)
    for value in range(256):
        cpu.m[0x700] = value
        cpu.run(0x96D0)
        check(cpu.m[0x700] == max(-99, min(99, signed8(value))) & 255, 'Fuji signed clamp')
        passed('F_native_clamp')
    cpu = CPU(image, {0x22: 0x8C, 0x23: 1}, mask=mask)
    cpu.set_fsr(2, 4)
    cpu.run(0x8B00)
    check(cpu.get_fsr(2) == 0x190, 'Fuji object offset')
    passed('F_native_pointer')
    for digit in range(10):
        for flag in (0, 128):
            cpu = CPU(image, {0xB1: 0x88, 0xB2: digit, 0x88: flag}, mask=mask)
            cpu.run(0xA6BA)
            check(cpu.m[0x88] == flag | image[0x41C9 - 0x4000 + digit], 'Fuji glyph table')
            passed('F_native_glyph')
    image, mask = stocks['O']
    glyphs = list(image[0x417D-0x4000:0x4187-0x4000])
    for row, flagaddr, shift in ((0x8B, 0x8A, 6), (0x8D, 0x91, 0), (0x8F, 0x91, 2)):
        for value in range(-99, 101):
            cpu = CPU(image, {0xB7: 0x8A, 0xB8: row, 0xB9: value & 255}, mask=mask)
            cpu.run(0x742E)
            absolute = abs(value)
            expected = bytes((glyphs[1], glyphs[0])) if value == 100 else bytes((glyphs[absolute // 10] | 128, glyphs[absolute % 10]))
            flags = (0 if value == 0 else 2 if value < 0 else 3) << shift
            check(bytes(cpu.m[row:row+2]) == expected and cpu.m[flagaddr] & (3 << shift) == flags, 'Olympus formatter %d row%X' % (value, row))
            check(not cpu.events, 'Olympus formatter must use real helpers')
            passed('O_native_formatter')
    image, mask = stocks['N']
    payload = bytes((0x27, 255, 255, 255, 1, 0x11, 11, 22, 33, 44, 55, 66, 63, 42, 0, 0))
    for count, index in ((0, 0), (0, 95), (82, 95), (83, 95), (84, 95), (99, 95), (100, 95)):
        cpu = CPU(image, {0x18: 0x1D, 0x93: index, 0x94: (index-count) % 100,
                         0x95: count, 0x96: 100, 0x97: 0, 0x98: 4}, mask=mask)
        cpu.m[0x1D:0x2D] = payload
        cpu.run(0x9D54)
        check(cpu.w == int(count < 84) and bytes(cpu.m[0x1D:0x2D]) == payload, 'Nikon queue result')
        if count < 84:
            check(cpu.m[0x95] == count + 17 and cpu.m[0x93] == (index+17) % 100, 'Nikon queue count')
            check(bytes(cpu.m[0x400+(index+i) % 100] for i in range(17)) == b'\0' + payload, 'Nikon queue bytes')
        else:
            check(cpu.m[0x95] == count and cpu.m[0x93] == index and not any(cpu.m[0x400:0x464]), 'Nikon full queue unchanged')
        passed('N_native_queue')
        if count == 0:
            cpu.m[0x1C] = 0x21
            cpu.m[0x1D] = 1
            cpu.run(0x5E34)
            check(bytes(cpu.m[0x121:0x128]) == bytes((0, 21, 0, 3, 0, 0, 0)), 'Nikon transport descriptor')
            check(bytes(cpu.m[0x128:0x13D]) == b'RSGT1' + payload, 'Nikon transport frame')
            check(cpu.m[0x95] == 0 and cpu.m[0x94] == (index + 17) % 100, 'Nikon queue drained')
            passed('N_native_frame_builder')
    image, mask = stocks['F']
    cpu = CPU(image, {0xBB: 0xC0}, mask=mask)
    cpu.m[0xC0:0xD0] = payload
    cpu.m[0x92:0x98] = bytes((0, 0, 0, 100, 0, 5))
    cpu.run(0xA60A)
    check(cpu.w == 1 and cpu.m[0x92] == 17 and cpu.m[0x93] == 0 and cpu.m[0x94] == 17 and bytes(cpu.m[0x500:0x511]) == b'\0' + payload, 'Fuji native enqueue')
    passed('F_native_queue')


def main():
    arithmetic_tests()
    indirect_tests()
    control_and_boundary_tests()
    native_helpers()
    print(json.dumps({
        'status': 'PASS_BOUNDED_VM_AND_STOCK_HELPERS',
        'cases_passed': sum(COUNTS.values()), 'cases': COUNTS,
        'vm_sha256': hashlib.sha256((HERE/'pic18_vm.py').read_bytes()).hexdigest(),
        'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'stock_sha256': STOCK_SHA, 'mask_sha256': MASK_SHA,
        'python': sys.version.split()[0], 'optimized': not __debug__,
        'hardware_accessed': False, 'updater_executed': False,
        'native_helper_replacements': 0,
        'scope': 'Finite instruction and stock helper checks, not device timing, RAM capacity, IRQ, Flash programming or RF hardware validation.'
    }, indent=2))


if __name__ == '__main__':
    main()
