#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Offline linked N stock/core/backend/hook replay; no executable package."""
from pathlib import Path
import hashlib
import json
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'shared'))
from pic18_vm import CPU
import runtime_generator
import native_backend
import native_hooks

STOCK = (HERE.parent/'shared/stock/N/original.base4000.partial.bin').read_bytes()
MASK = (HERE.parent/'shared/stock/N/original.known_mask.bin').read_bytes()
STATE = 0x680


def check(ok, message):
    if not ok:
        raise RuntimeError(message)


def link():
    profile = dict(model_tag='N', state_base=STATE, state_span=0x180,
                   window_counts=200, stable_counts=20, clock_mask=0xFFFF,
                   code_limit=0xF800, nv_enabled=False)
    backend = native_backend.construct(STOCK, code_base=0xAA80)
    core_start = 0xAA80 + len(backend['sections'][0]['data'])
    core = runtime_generator.construct(STOCK, code_base=core_start, profile=profile, backend=backend)
    backend = native_backend.construct(STOCK, code_base=0xAA80, imports=core['exports'])
    hooks_start = core_start + len(core['sections'][0]['data'])
    hooks = native_hooks.construct(STOCK, code_base=hooks_start, imports=core['exports'],
                                   backend_exports=backend['exports'], profile=profile)
    image = bytearray(STOCK)
    for component in (backend, core, hooks):
        for section in component['sections']:
            offset = section['address']-0x4000
            image[offset:offset+len(section['data'])] = section['data']
    for hook in hooks['hooks']:
        offset = hook['address']-0x4000
        image[offset:offset+len(bytes.fromhex(hook['new_hex']))] = bytes.fromhex(hook['new_hex'])
    return image, backend, core, hooks


def main():
    image, backend, core, hooks = link()
    counts = {'startup_context':0, 'select_context':0, 'power_context':0,
              'native_queue':0, 'idle_context':0, 'secondary_context':0, 'fallback':0}
    counts['ttl_def_idle_gate'] = 0
    for mode in (0, 1):
        for seed in (0x13, 0xA7):
            values = {address:(address*17+seed)&255 for address in native_hooks.CONTEXT}
            for high in (0xFEA, 0xFE2, 0xFDA):
                values[high] &= 0x0F
            values[0xFF8] &= 0x3F
            values.update({0x49:0xB1,0x4A:1,0x1B1:mode,0x60:1,0x47:3,0x48:0,
                           0x4C:7,0x50:0,0x96:100,0x97:0,0x98:4})
            c = CPU(image, values, mask=MASK)
            c.m[STATE:STATE+0x180] = bytes([seed])*0x180
            reference = CPU(STOCK, values, mask=MASK)
            reference.run(0x4CF2, stops=(0x4CF6,))
            before = {address:reference.m[address] for address in native_hooks.CONTEXT}
            c.run(0x4CF2, stops=(0x4CF6,), max_steps=30000)
            check(c.m[STATE] == 0xA8 and c.m[STATE+1] == mode, 'startup did not initialize core')
            check(all(c.m[address] == value for address,value in before.items()), 'startup outer context changed')
            counts['startup_context'] += 1
            c.m[0xC0], c.m[0xC1] = 0x7E, 2
            before = {address:c.m[address] for address in native_hooks.CONTEXT}
            c.run(0x55EC, max_steps=30000)
            check(c.m[STATE+4] == 2 and c.m[0x60] == 2, 'B press failed to select B')
            check(all(c.m[address] == value for address,value in before.items()), 'select outer context changed')
            counts['select_context'] += 1
            c.w = 1
            before = {address:c.m[address] for address in native_hooks.CONTEXT}
            c.run(0x7E0A, max_steps=30000)
            check(c.m[STATE+(0x15 if mode == 0 else 0x0F)] == 1, 'power native step not applied')
            check(c.m[STATE+0x28] == 1 and c.m[0x95] == 0, 'power must plan once, not call original radio callback')
            check(c.m[0x99] == c.m[0x9A] == c.m[0x9B] == 0, 'native MAN callback leaked')
            check(all(c.m[address] == value for address,value in before.items()), 'power outer context changed')
            counts['power_context'] += 1
            # An edit rejected during an outstanding plan must not fall through
            # to the original relative sender or mutate its scratch state.
            c.run(0x7E0A, max_steps=30000)
            check(c.m[STATE+(0x15 if mode == 0 else 0x0F)] == 1 and c.m[0x95] == 0, 'rejected edit fell through')
            counts['power_context'] += 1
            c.run(core['exports']['service'], max_steps=30000)
            check(c.m[0x95] == 17, 'service did not admit exactly one original-queue frame')
            frame = bytes(c.m[0x401:0x411])
            expected = (bytes((0x27,255,255,255,1,0x25,0,1,0,0,0,0,0,0,0,0)) if mode == 0
                        else bytes((2,255,255,255,1,6,2,0,0,0,0,0,0,0,0,0)))
            check(frame == expected, 'wrong native radio frame ' + frame.hex())
            counts['native_queue'] += 1
            # Independently exercise the original idle-expiry call replacement.
            # Explicit downstream-consumer boundary: the just-enqueued frame
            # has now been consumed. M2 correctly refuses idle clearing while
            # the native radio queue still owns that frame; this success case
            # must not silently leave its old count of 17 bytes pending.
            c.m[0x94] = (c.m[0x94] + c.m[0x95]) % 100
            c.m[0x95] = 0
            c.m[STATE+0x28] = 0  # expired-idle scenario, no active TX plan
            c.m[STATE+0x0E:STATE+0x14] = bytes((1,2,3,4,5,6)); c.m[STATE+7] = 0x3F
            before = {address:c.m[address] for address in native_hooks.CONTEXT}
            c.run(hooks['exports']['idle_hook'], max_steps=30000)
            check(not any(c.m[STATE+0x0E:STATE+0x14]) and c.m[STATE+7] == 0, 'idle deadline did not clear AIR1 values')
            check(all(c.m[address] == value for address,value in before.items()), 'idle outer context changed')
            counts['idle_context'] += 1
    # Every low-frequency button goes to the shared gesture entry, not native
    # selection/Head/Model callbacks. Released native single remains valid.
    for low, first in ((0x82,1),(0x86,2),(0x8A,4)):
        c = CPU(image,{0x49:0xB1,0x4A:1,0x1B1:1,0x60:1,0x47:3,0x4C:7},mask=MASK)
        c.run(0x4CF2,stops=(0x4CF6,),max_steps=30000)
        c.m[0xC0],c.m[0xC1] = low,2
        before = {address:c.m[address] for address in native_hooks.CONTEXT}
        c.run(0x55EC,max_steps=30000)
        check(c.m[STATE+0x18] == 1 and c.m[STATE+0x19] == first, 'secondary press not deferred')
        check(c.m[0x95] == 0 and c.m[0x4C] == 7 and c.m[0x50] == 0, 'secondary caused original side effect')
        check(all(c.m[address] == value for address,value in before.items()), 'secondary outer context changed')
        counts['secondary_context'] += 1
    for disabled in ('magic','diagnostic'):
        c = CPU(image,{STATE:0 if disabled=='magic' else 0xA8,0x4D:1 if disabled=='diagnostic' else 0},mask=MASK)
        c.run(0x55EC,stops=(0x55F0,),max_steps=30000)
        check(c.pc == 0x55F0 and c.w == 0x72 and c.m[0xFE0] == 0, 'original press preimage not replayed')
        counts['fallback'] += 1
    for mode in (0,1):
        for page in (0,1):
            for manual in (1,2):
                c = CPU(image,{0x49:0xB1,0x4A:1,0x1B1:mode,STATE:0xA8,
                               STATE+1:mode,STATE+2:manual,STATE+3:page},mask=MASK)
                c.run(0x7B52,stops=(0x7B62,0x7B80),max_steps=30000)
                expected = 0x7B62 if mode==1 or (page==1 and manual==1) else 0x7B80
                check(c.pc==expected, 'TTL-DEF AIR1 did not use original idle deadline')
                counts['ttl_def_idle_gate'] += 1
    report = {'status':'PASS_LINKED_STOCK_CORE_BACKEND_HOOK_REPLAY','cases':sum(counts.values()),'counts':counts,
              'source_sha256':hashlib.sha256(STOCK).hexdigest(),'linked_image_sha256':hashlib.sha256(image).hexdigest(),
              'components':{name:hashlib.sha256((HERE/path).read_bytes()).hexdigest() for name,path in
                            (('backend','native_backend.py'),('hooks','native_hooks.py'))},
              'core_sha256':hashlib.sha256((HERE.parent/'shared/runtime_generator.py').read_bytes()).hexdigest(),
              'vm_sha256':hashlib.sha256((HERE.parent/'shared/pic18_vm.py').read_bytes()).hexdigest(),
              'native_helper_replacements':0,'core_replacements':0,'hardware_accessed':False,
              'limitations':['service wrapper original hardware scheduler and LCD serializer not exercised',
                            'event timing/physical RAM/RF/NVM qualification belongs to integration gate',
                            'profile clock values are replay inputs, not validated physical timing']}
    (HERE/'native_hooks_test_results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
