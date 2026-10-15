#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay N adapter machine code against original native helpers; no hardware."""
from pathlib import Path
import hashlib
import itertools
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'shared'))
from pic18_vm import CPU
from native_backend import construct, Asm

STOCK = (HERE.parent / 'shared/stock/N/original.base4000.partial.bin').read_bytes()
MASK = (HERE.parent / 'shared/stock/N/original.known_mask.bin').read_bytes()
BASE = 0x680
BUILD = construct(STOCK, imports={'display_row': 0xD000})
IMAGE = bytearray(STOCK)
for section in BUILD['sections']:
    off = section['address'] - 0x4000
    IMAGE[off:off+len(section['data'])] = section['data']


def check(ok, message):
    if not ok:
        raise RuntimeError(message)


def cpu(values=None, image=IMAGE):
    valid = {0x49:0xB1, 0x4A:1, 0x60:1, 0x47:3}
    return CPU(image, valid | dict(values or {}), mask=MASK)


def run(c, name):
    c.run(BUILD['exports'][name], max_steps=20000)


def main():
    counts = {'snapshots': 0, 'queue': 0, 'lcd': 0, 'page_hint':0, 'apply': 0, 'nv': 0, 'nv_readiness':0}
    for mode, selector, secondary, other in itertools.product((0, 1), (1, 2, 3, 7), range(8), range(2)):
        c = cpu({0x49: 0xB1, 0x4A: 1, 0x1B1: mode, 0x60: selector,
                 0x47: 3, 0x48: 0, 0x4C: 5, 0x50: 6,
                 0x1B5: 236, 0x1B6: 0, 0x1B7: 20,
                 0x11B: 0x34, 0x11C: 0x12})
        for bit, obj in enumerate((0x282, 0x286, 0x28A)):
            c.m[obj] = (secondary >> bit) & 1
        c.m[0x28E] = other
        c.m[BASE:BASE+0x70] = b'\xA5' * 0x70
        run(c, 'read_inputs')
        expected = bytes((mode, selector, 5, 6, 236, 0, 20, 0x83, 0x34, 0x12, secondary, other, 0, 0, 0, 0))
        check(c.w == 1 and bytes(c.m[BASE+0x70:BASE+0x80]) == expected,
              'input snapshot mismatch: ' + repr((mode, selector, secondary, other, c.w, list(c.m[BASE+0x70:BASE+0x80]))))
        check(c.m[BASE:BASE+0x70] == b'\xA5' * 0x70, 'snapshot overwrote canonical state')
        counts['snapshots'] += 1
    defaults = {0x49: 0xB1, 0x4A: 1, 0x60: 1, 0x47: 3}
    for addr, value, flags in ((0x49, 0, 0), (0x1B1, 2, 0), (0x60, 0, 0),
                               (0x47, 2, 0x80), (0x4D, 1, 0x80), (0x4B, 1, 0x80),
                               (0x85, 1, 0x80), (0x1B8, 1, 0x80), (0x2BA, 1, 0x81), (0x95, 1, 0x81)):
        c = cpu(defaults | {addr: value}); run(c, 'read_inputs')
        check(c.m[BASE+0x77] == flags and c.w == int(flags != 0), 'snapshot unsafe gate')
        counts['snapshots'] += 1
    payload = bytes((0x27, 255, 255, 255, 1, 0x11, 11, 22, 33, 44, 55, 66, 63, 42, 0, 0))
    for count, index in itertools.product((0, 1, 83, 84, 100), (0, 95)):
        c = cpu({0x93: index, 0x94: (index-count) % 100, 0x95: count, 0x96: 100, 0x97: 0, 0x98: 4})
        c.m[BASE+0x30:BASE+0x40] = payload
        run(c, 'tx_frame')
        check(c.w == int(count == 0), 'adapter queue admission policy')
        check(bytes(c.m[BASE+0x30:BASE+0x40]) == payload, 'adapter mutated source frame')
        if count == 0:
            check(c.m[0x95] == 17 and bytes(c.m[0x400+(index+i)%100] for i in range(17)) == b'\0'+payload, 'native queue content')
        else:
            check(c.m[0x95] == count and not any(c.m[0x400:0x464]), 'busy queue changed')
        counts['queue'] += 1
    for gate in (0x4B, 0x4D, 0x85, 0x1B8, 0x2BA):
        c = cpu({gate: 1}); run(c, 'tx_frame')
        check(c.w == 0 and c.m[0x95] == 0, 'exclusive gate failed')
        counts['queue'] += 1
    glyphs = list(STOCK[0x4183-0x4000:0x418D-0x4000])
    for kind, value, page, selection in itertools.product(range(4), (0, 1, 9, 10, 20, 55, 99, 100, 236), (0, 1), (1, 7)):
        if kind == 2 and value not in range(1, 101):
            continue
        # Explicit stand-in for shared core display_row; no native LCD helper is
        # replaced. Its only purpose is to exercise the six-import ABI boundary.
        stub = Asm(0xD000); stub.put(BASE+0x61, value); stub.ret(kind)
        image = bytearray(IMAGE); image[0x9000:0x9000+len(stub.data)] = stub.data
        c = cpu({BASE+3: page, BASE+4: selection, BASE+5: 0x3F, BASE+6: 0x2A, BASE+0xB4:page}, image)
        run(c, 'redraw')
        if kind == 0:
            numeric = bytes((0, 0))
        elif kind == 3:
            numeric = bytes((0x10, 0x10))
        else:
            magnitude = abs(value if value < 128 else value-256)
            numeric = bytes((glyphs[1], glyphs[0])) if magnitude == 100 else bytes((glyphs[magnitude//10] | 128, glyphs[magnitude % 10]))
        for row in (0x89, 0x8B, 0x8D):
            check(bytes(c.m[row:row+2]) == numeric, 'LCD numeric mismatch ' + repr((kind,value,page,selection,row,bytes(c.m[row:row+2]),numeric)))
        check(c.m[0x88] & 0x15 == (0x15 if page == 0 else 0), 'ABC fixed symbol mask')
        check(c.m[0x88] & 0x2A == (0x2A if selection == 7 else 2), 'LCD selection')
        check(c.m[0x8F] & 0xD0 == (0x40 if page == 0 else 0x90), 'model page projection')
        if kind != 1:
            check(c.m[0x88] & 0xC0 == 0 and c.m[0x8F] & 0x0F == 0, 'absolute/blank/off retained signs')
        counts['lcd'] += 1
    stub = Asm(0xD000); stub.put(BASE+0x61, 50); stub.ret(2)
    image = bytearray(IMAGE); image[0x9000:0x9000+len(stub.data)] = stub.data
    c = cpu({BASE+3:1,BASE+4:1,BASE+5:0x3F,0x11B:0xDC,0x11C:0xFF},image)
    for tick,active,page in ((0xFFDC,True,1),(613,True,1),(614,False,1),(615,True,0),(1265,False,0)):
        c.m[0x11B]=tick&255; c.m[0x11C]=tick>>8; c.m[BASE+3]=page
        run(c,'redraw')
        for row,numeric in ((1,0x89),(2,0x8B),(3,0x8D)):
            expected = bytes((STOCK[0x4183-0x4000+(12+row if page else 9+row)],0)) if active else bytes((glyphs[5]|128,glyphs[0]))
            check(bytes(c.m[numeric:numeric+2])==expected, 'page cue native tick/wrap mismatch')
        counts['page_hint'] += 1
    for head, model, page in itertools.product(range(64), (0, 7, 0x38, 0x3F), (0,1)):
        c = cpu({BASE+3:page, BASE+5:head, BASE+6:model, 0x4C:0xA8, 0x50:0xC0})
        c.w = 8; run(c, 'apply_native_state')
        check(c.w == 1 and c.m[0x4C] == (0xA8 | head & 7) and c.m[0x50] == (0xC0 | model & 7), 'canonical ABC native mask')
        counts['apply'] += 1
    for requested, old in itertools.product((0,1), repeat=2):
        c = cpu({BASE+1:requested, 0x1B1:old, 0x49:0xB1, 0x4A:1, 0x60:1})
        c.w=1; run(c,'apply_native_state')
        check(c.w == 1 and c.m[0x1B1] == requested and c.m[0x95] == 0, 'mode application or unintended radio')
        if requested != old:
            check(int.from_bytes(c.m[0x69:0x6C], 'little') == (0x8914 if requested == 0 else 0x8B4E), 'mode callback not rebound')
        counts['apply'] += 1
    for name in ('nv_load','nv_commit'):
        c = cpu(); run(c,name); check(c.w == 0, 'NVM stub claimed success'); counts['nv'] += 1
    nv_backend=construct(STOCK,imports={'display_row':0xD000},
                         profile={'nv_enabled':True,'native_nv_gate_proven':True})
    nv_image=bytearray(STOCK)
    for sec in nv_backend['sections']:
        off=sec['address']-0x4000; nv_image[off:off+len(sec['data'])]=sec['data']
    for gate,value in ((None,0),(0x282,1),(0x286,1),(0x28A,1),(0x28E,1),
                        (BASE+0x18,1),(BASE+0x28,1),(0x1CC,1),(0x53,2),
                        (0xFF0,1),(0xFF0,2),(0xF9E,0x20),(0xFAD,0)):
        vals={0xFF0:0,0xF9E:0,0xFAD:2,0xFF2:0}
        if gate is not None: vals[gate]=value
        c=cpu(vals,nv_image); c.run(nv_backend['exports']['read_inputs'])
        check(c.m[BASE+0x77] == (0x87 if gate is None else 0x83), 'fresh NV-ready gate mismatch')
        check(c.m[0xFF2] == 0, 'read_inputs reenabled masked IRQ')
        counts['nv_readiness'] += 1
    report = {'status':'PASS_BOUNDED_NATIVE_BACKEND_REPLAY', 'counts':counts,
              'cases':sum(counts.values()), 'stock_sha256':hashlib.sha256(STOCK).hexdigest(),
              'backend_sha256':hashlib.sha256((HERE/'native_backend.py').read_bytes()).hexdigest(),
              'vm_sha256':hashlib.sha256((HERE.parent/'shared/pic18_vm.py').read_bytes()).hexdigest(),
              'native_helper_replacements':0,'synthetic_core_display_provider':True,
              'hardware_accessed':False,'flashable_image_generated':False,
              'limits':['finite replay only; not IRQ/timing or complete original-program RAM proof',
                        'hooks and NVM not implemented by this test']}
    (HERE/'native_backend_test_results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
