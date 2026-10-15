#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Execute linked M2 startup restoration regressions, without hardware I/O.

Each model runs in a fresh process. Native routines and the shared core execute
as PIC18 instructions. Explicit boundaries are the existing Flash controller
model and one test's externally changing native busy byte; no code is replaced.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TARGETS = (25, 35, 45, 55, 65, 75)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def record(tag, effective=2, head=0x2A, model=0x35):
    body = bytes((0x41, 0x32, 5, effective, 9, 0, *TARGETS,
                  head, model, 1, 2, ord(tag))) + bytes(11)
    return body + binascii.crc_hqx(body, 0xFFFF).to_bytes(2, 'little') + b'\x5a\xa5'


def decode(raw):
    require(len(raw) == 32 and raw[:3] == b'A2\x05' and raw[-2:] == b'\x5a\xa5',
            'incomplete V5 record')
    require(binascii.crc_hqx(raw[:28], 0xFFFF) == int.from_bytes(raw[28:30], 'little'),
            'record CRC mismatch')
    return dict(effective=raw[3], sequence=int.from_bytes(raw[4:6], 'little'),
                targets=list(raw[6:12]), head=raw[12], model=raw[13], page=raw[14],
                last_manual=raw[15], tag=chr(raw[16]))


def run_model(tag):
    import build_variants
    from test_integrated_firmware import Machine, MODEL

    profile = json.loads((ROOT/tag/'port_profile.json').read_text(encoding='utf-8'))
    linked = build_variants.link(tag, profile)
    contract = MODEL[tag]
    rows = []

    def new(mode=1, flash=None, values=None):
        return Machine(tag, linked['image'], linked['mask'], profile,
                       linked['components'], mode=mode, flash=flash,
                       native_values=values)

    def stored(effective=2, raw=None, head=0x2A, model=0x35):
        data = bytearray(new().cpu.flash)
        data[0xF800:0xF820] = record(tag, effective, head, model) if raw is None else raw
        return bytes(data)

    def state(m):
        return dict(mode=m.state(1), last_manual=m.state(2), page=m.state(3),
                    head=m.state(5), model=m.state(6), targets=list(m.state(8, 6)),
                    flags=m.state(0x17), native_mode=m.cpu.m[contract['mode']],
                    native_head=m.cpu.m[contract['head']] & 7,
                    native_model=m.cpu.m[contract['model']] & 7,
                    native_winner=m.state(0x2D), flash_words=len(m.flash.operations))

    def masks(m, head=0x2A, model=0x35, native=False):
        require(m.state(5) == head and m.state(6) == model, 'saved masks overwritten')
        require(tuple(m.state(8, 6)) == TARGETS and m.state(3) == 1 and m.state(2) == 2,
                'saved targets/page/last-manual overwritten')
        if native:
            require(m.cpu.m[contract['head']] & 7 == head & 7
                    and m.cpu.m[contract['model']] & 7 == model & 7,
                    'saved ABC masks not projected to native state')

    def pending(m):
        masks(m)
        require(m.state(0x17) & 2, 'restore pending cleared before projection')
        require(not m.flash.operations and m.cpu.m[contract['descriptor']+2] == 0,
                'unprojected restore saved NVM or queued RF')

    def durable(m, final_mode):
        require(not m.state(0x17) & 2 and m.state(1) == final_mode
                and m.cpu.m[contract['mode']] == final_mode,
                'mode winner was overridden or pending did not finish')
        masks(m, native=True)
        m.call('service')
        original = decode(bytes(m.cpu.flash[0xF800:0xF820]))
        changed = original['effective'] != (2 if final_mode else 0)
        address = 0xF820 if changed else 0xF800
        latest = decode(bytes(m.cpu.flash[address:address+32]))
        require(latest == dict(effective=2 if final_mode else 0, sequence=10 if changed else 9,
                              targets=list(TARGETS), head=0x2A, model=0x35,
                              page=1, last_manual=2, tag=tag), 'wrong durable record')
        require(len(m.flash.operations) == (16 if changed else 0),
                'expected one changed record or deduplicated unchanged state')
        reboot = new(mode=1-final_mode, flash=bytes(m.cpu.flash))
        reboot.call('init')
        masks(reboot, native=True)
        require(reboot.state(1) == final_mode and not reboot.flash.operations,
                'durable state did not survive reboot without writes')
        return dict(final=state(m), record=latest, reboot=state(reboot))

    for saved_mode, effective in ((1, 2), (0, 0)):
        for native_mode in (0, 1):
            m = new(mode=native_mode, flash=stored(effective))
            m.call('init'); masks(m, native=True)
            require(m.state(1) == saved_mode and m.cpu.m[contract['mode']] == saved_mode
                    and not m.state(0x17) & 2 and not m.flash.operations,
                    'ordinary boot restoration changed')
            rows.append(dict(name='ready_boot', saved_mode=saved_mode,
                             initial_native=native_mode, result=state(m)))

        # Exact M1 counterexample: an external mode transition first becomes
        # observable in the same service call which clears native busy.
        original = 1-saved_mode
        m = new(mode=original, flash=stored(effective), values={contract['busy_input']: 1})
        m.call('init'); pending(m)
        m.cpu.m[contract['mode']] = saved_mode
        m.cpu.m[contract['busy_input']] = 0
        m.call('service')
        rows.append(dict(name='audit_counterexample_fixed', saved_mode=saved_mode,
                         **durable(m, saved_mode)))

        # A mode event is accepted while still busy. Actual masks-only apply
        # must refuse repeatedly, retain pending intent and block UI edits.
        for flip_back in (False, True):
            m = new(mode=original, flash=stored(effective),
                    values={contract['busy_input']: 1})
            m.call('init'); pending(m)
            m.cpu.m[contract['mode']] = saved_mode
            for _ in range(6):
                m.call('service'); pending(m)
            require(m.state(0x2D) == 2 and m.state(1) == saved_mode,
                    'external mode winner not latched during apply failure')
            require(m.call('power_edit', 1) == 0, 'edit accepted before boot projection')
            pending(m)
            final_mode = original if flip_back else saved_mode
            m.cpu.m[contract['mode']] = final_mode
            m.call('service'); pending(m)
            m.cpu.m[contract['busy_input']] = 0
            m.call('service')
            rows.append(dict(name='busy_retry_native_flip_back' if flip_back else 'busy_retry',
                             saved_mode=saved_mode, **durable(m, final_mode)))

        # Input snapshot initially sees idle, then a later read of the busy
        # input sees busy. Actual backend refusal and successful retry execute.
        m = new(mode=original, flash=stored(effective), values={contract['busy_input']: 1})
        m.call('init'); pending(m)
        m.cpu.m[contract['mode']] = saved_mode
        m.cpu.m[contract['busy_input']] = 0
        busy_reads = []
        def busy_changes(cpu):
            value = cpu.m[contract['busy_input']]
            busy_reads.append(dict(pc=cpu.pc, value=value))
            cpu.m[contract['busy_input']] = 1
            return value
        m.cpu.read_hooks[contract['busy_input']] = busy_changes
        m.call('service'); pending(m)
        require(len(busy_reads) >= 2 and busy_reads[0]['value'] == 0
                and busy_reads[1]['value'] == 1, 'fresh readiness boundary not exercised')
        m.cpu.read_hooks.pop(contract['busy_input'])
        m.cpu.m[contract['busy_input']] = 0
        m.call('service')
        rows.append(dict(name='fresh_gate_refusal_then_retry', saved_mode=saved_mode,
                         input_events=busy_reads, **durable(m, saved_mode)))

        # Invalid native state must not be mistaken for a camera mode event.
        m = new(mode=original, flash=stored(effective), values={contract['busy_input']: 1})
        m.call('init'); pending(m)
        m.cpu.m[contract['mode']] = 3
        for _ in range(3):
            m.call('service'); pending(m)
        require(m.state(1) == saved_mode and m.state(0x2D) == original,
                'invalid native input replaced saved mode intent')
        m.cpu.m[contract['mode']] = original
        m.cpu.m[contract['busy_input']] = 0
        m.call('service'); masks(m, native=True)
        require(m.state(1) == saved_mode and not m.state(0x17) & 2
                and not m.flash.operations, 'valid retry after invalid input failed')
        rows.append(dict(name='invalid_native_snapshot_then_retry', saved_mode=saved_mode,
                         result=state(m)))

    for head, model in ((0, 0), (63, 63)):
        m = new(mode=0, flash=stored(head=head, model=model),
                values={contract['busy_input']: 1})
        m.call('init'); masks(m, head, model)
        m.cpu.m[contract['mode']] = 1
        m.cpu.m[contract['busy_input']] = 0
        m.call('service'); masks(m, head, model, native=True)
        require(not m.state(0x17) & 2, 'mask edge-value projection remains pending')
        rows.append(dict(name='mask_edge_values', head=head, model=model, result=state(m)))

    invalid = {}
    invalid['no_record'] = bytes([255])*32
    raw = bytearray(record(tag)); raw[28] ^= 1; invalid['bad_crc'] = bytes(raw)
    raw = bytearray(record(tag)); raw[30] = 255; invalid['incomplete_commit'] = bytes(raw)
    invalid['wrong_model'] = record('S' if tag != 'S' else 'N')
    for name, offset, value in (('zero_target', 6, 0), ('invalid_head', 12, 64),
                                ('invalid_mode', 3, 3), ('invalid_page', 14, 2)):
        raw = bytearray(record(tag)); raw[offset] = value
        raw[28:30] = binascii.crc_hqx(raw[:28], 0xFFFF).to_bytes(2, 'little')
        invalid[name] = bytes(raw)
    for name, raw in invalid.items():
        m = new(mode=0, flash=stored(raw=raw),
                values={contract['head']: 2, contract['model']: 5})
        m.call('init'); m.call('service')
        require((m.state(1), m.state(2), m.state(3), m.state(5), m.state(6)) == (0, 1, 0, 2, 5)
                and list(m.state(8, 6)) == [50]*6 and not m.state(0x17)
                and not m.flash.operations and m.cpu.m[contract['descriptor']+2] == 0,
                'invalid/absent record altered safe native defaults: '+name)
        rows.append(dict(name=name, result=state(m)))

    labels = linked['components']['core']['labels']
    return dict(status='PASS', model=tag, count=len(rows), python_optimization=sys.flags.optimize,
                image_sha256=hashlib.sha256(linked['image']).hexdigest(),
                runtime_sha256=hashlib.sha256((HERE/'runtime_generator.py').read_bytes()).hexdigest(),
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                addresses={name:hex(labels[name]) for name in
                           ('init', 'boot_projection', 'boot_native_changed', 'boot_apply_projection', 'service')},
                cases=rows,
                boundary='Linked actual core/native/PIC18 journal instructions; supplied Flash MMIO model and declared busy-input mutation only. No firmware helper replacement, USB, reset-vector, bootloader, physical ISR/clock or RF execution.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=tuple('NSFO'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.model:
        result = run_model(args.model)
    else:
        models = {}
        for tag in 'NSFO':
            command = [sys.executable, '-X', 'utf8', '-B']
            if sys.flags.optimize:
                command.append('-O')
            command += [str(Path(__file__).resolve()), '--model', tag]
            completed = subprocess.run(command, check=True, text=True,
                                       encoding='utf-8', capture_output=True)
            models[tag] = json.loads(completed.stdout)
        result = dict(status='PASS', count=sum(m['count'] for m in models.values()),
                      python_optimization=sys.flags.optimize, models=models)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding='utf-8')
        print(json.dumps(dict(status=result['status'], count=result['count'], output=str(args.out))))
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
