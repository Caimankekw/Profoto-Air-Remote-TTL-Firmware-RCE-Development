#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Replay N/O real native expiry callers, including deferred AIR1 retry.

Run this model-local copy in a fresh process. It uses shared VM/linker files
and this model's sources only; an optional frozen M1 build proves the original
counterexample. No installer, hardware, native helper replacement or RF model
is executed. Timers use original encoded counts, not assumed milliseconds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
TAG = HERE.name
SHARED = HERE.parent / 'shared'
sys.path.insert(0, str(SHARED))
from build_variants import link
from test_integrated_firmware import Machine, check

PARAMS = {
    'N': dict(entry=0x7B52, stop=0x7B80, deadline=0xB4, coarse=0x119,
              camera=0x4B, stock_clear=0xA8C0),
    'O': dict(entry=0x7FA0, stop=0x7FCC, deadline=0xAD, coarse=0x73,
              camera=0x2D, stock_clear=0xAA38),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_current():
    profile = json.loads((HERE / 'port_profile.json').read_text('utf-8'))
    return link(TAG, profile)


def load_frozen(directory):
    profile = json.loads((directory / 'profile.json').read_text('utf-8'))
    matches = list(directory.glob('*.partial.bin'))
    check(len(matches) == 1, 'expected one frozen application image')
    return dict(profile=profile, image=matches[0].read_bytes(),
                mask=(SHARED / 'stock' / TAG / 'original.known_mask.bin').read_bytes(),
                components=json.loads((directory / 'linked_components.json').read_text('utf-8')))


def make(result, path, kind=1, page=None):
    mode = 1 if path == 'MAN' else 0
    m = Machine(TAG, result['image'], result['mask'], result['profile'],
                result['components'], mode=mode)
    m.call('init')
    m.set_state(2, kind)
    m.set_state(3, (0 if mode else 1) if page is None else page)
    m.set_state(7, 1 if mode else 8)
    m.set_state(0x0E, bytes((10, 11, 12, 13, 14, 15)))
    m.set_state(0x14, bytes((2, 3, 4)))
    m.cpu.m[m.contract['fec']:m.contract['fec']+3] = bytes((2, 3, 4))
    m.cpu.track_trace = True
    return m


def timer(m, deadline, now=0):
    p = PARAMS[TAG]
    m.cpu.m[p['deadline']:p['deadline']+2] = deadline.to_bytes(2, 'little')
    m.cpu.m[p['coarse']:p['coarse']+2] = (now & 0x7FFF).to_bytes(2, 'little')


def observe(m):
    d = PARAMS[TAG]['deadline']
    return dict(visible=m.state(7), relative=m.state(0x0E, 6).hex(),
                deadline=int.from_bytes(m.cpu.m[d:d+2], 'little'),
                pending=m.state(0x28), fec=m.state(0x14, 3).hex())


def native_expiry(m, path):
    before = len(m.cpu.trace)
    if TAG == 'O' and path == 'TTL_DEF':
        # Real foreground service first executes stock 75AC; no helper stub.
        m.call('service', group='hooks')
    else:
        m.cpu.run(PARAMS[TAG]['entry'], stops=(PARAMS[TAG]['stop'],), max_steps=150000)
    check(not m.cpu.stack, 'GOTO expiry continuation leaked a hardware return frame')
    check(not any(e[0] == 'step_hook' for e in m.cpu.events), 'native helper replacement')
    return m.cpu.trace[before:]


def blocker(m, name, enabled):
    if name == 'pending':
        m.set_state(0x28, int(enabled))
        m.set_state(0x29, 1 if m.state(1) else 4)
        m.set_state(0x2A, 1 if m.state(1) else 8)
        m.set_state(0x2B, 1)
        m.set_state(0x2C, 1)
        # The O native service runs before expiry and could finish this plan.
        # Preserve a real pending plan using its existing native camera gate.
        if TAG == 'O':
            m.cpu.m[PARAMS[TAG]['camera']] = int(enabled)
    elif name == 'native_busy':
        m.cpu.m[m.contract['busy_input']] = int(enabled)
    elif name == 'camera_busy':
        m.cpu.m[PARAMS[TAG]['camera']] = int(enabled)
    elif name == 'radio_busy':
        m.cpu.m[m.contract['descriptor']+2] = 17 if enabled else 0
    else:
        raise ValueError(name)


def verify(result):
    rows = []
    for path in ('MAN', 'TTL_DEF'):
        for reason in ('pending', 'native_busy', 'camera_busy', 'radio_busy'):
            for encoded, now, clock_case in ((0x8064, 100, 'ordinary'), (0xFFFE, 2, 'wrap')):
                m = make(result, path)
                timer(m, encoded, now)
                blocker(m, reason, True)
                first_trace = native_expiry(m, path)
                deferred = observe(m)
                check(deferred['visible'] and deferred['deadline'],
                      f'{path}/{reason}/{clock_case}: deferred clear consumed timer')
                check(PARAMS[TAG]['stock_clear'] not in first_trace,
                      'deferred native expiry called original timer disarm')
                check(deferred['relative'] == bytes((10, 11, 12, 13, 14, 15)).hex(),
                      'rejected expiry changed relative values')
                blocker(m, reason, False)
                second_trace = native_expiry(m, path)
                done = observe(m)
                check(done['visible'] == 0 and done['relative'] == bytes(6).hex()
                      and done['deadline'] == 0, 'idle retry did not clear and disarm')
                check(PARAMS[TAG]['stock_clear'] in second_trace, 'successful expiry omitted disarm')
                check(done['fec'] == '020304', 'AIR1 expiry changed TTL FEC')
                rows.append(dict(case=f'{path}/{reason}/{clock_case}', deferred=deferred, completed=done))

        m = make(result, path)
        timer(m, 0x8064, 99)
        native_expiry(m, path)
        check(m.state(7) and observe(m)['deadline'] == 0x8064, 'deadline expired early')
        timer(m, 0x8064, 100)
        native_expiry(m, path)
        check(m.state(7) == 0 and observe(m)['deadline'] == 0, 'exact deadline did not expire')
        rows.append(dict(case=f'{path}/native_deadline_boundary', completed=observe(m)))

        m = make(result, path)
        timer(m, 0, 123)
        native_expiry(m, path)
        check(m.state(7) and observe(m)['deadline'] == 0, 'inactive timer cleared relative state')
        rows.append(dict(case=f'{path}/inactive_timer'))

        m = make(result, path)
        timer(m, 0xFFFF)
        blocker(m, 'pending', True)
        native_expiry(m, path)
        m.set_state(2, 2)
        blocker(m, 'pending', False)
        original_targets = m.state(8, 6)
        native_expiry(m, path)
        check(m.state(8, 6) == original_targets and m.state(0x14, 3) == b'\x02\x03\x04',
              'A2 transition changed target or FEC')
        if path == 'MAN':
            check(observe(m)['deadline'] == 0, 'A2 MAN timer was incorrectly kept retrying')
        else:
            check(m.state(7) != 0 and observe(m)['deadline'] != 0,
                  'TTL DEF A2 should bypass AIR1 expiry')
        rows.append(dict(case=f'{path}/mode_change_to_A2', completed=observe(m)))

    m = make(result, 'TTL_DEF', page=0)
    timer(m, 0xFFFF)
    native_expiry(m, 'TTL_DEF')
    check(m.state(0x14, 3) == b'\x02\x03\x04' and m.state(7) != 0,
          'TTL ABC FEC path consumed the AIR1 expiry')
    rows.append(dict(case='TTL_ABC/FEC_negative', completed=observe(m)))
    return rows


def frozen_counterexamples(result):
    rows = []
    for path in ('MAN', 'TTL_DEF'):
        m = make(result, path)
        timer(m, 0xFFFF)
        blocker(m, 'pending', True)
        native_expiry(m, path)
        failed = observe(m)
        blocker(m, 'pending', False)
        native_expiry(m, path)
        after = observe(m)
        check(failed['visible'] and failed['deadline'] == 0 and after['visible'],
              'frozen M1 did not reproduce the expected lost-expiry counterexample')
        rows.append(dict(case=path, lost_deadline=failed, after_idle=after))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-directory', type=Path)
    parser.add_argument('--report', type=Path, default=HERE / 'idle_retry_m2_results.json')
    args = parser.parse_args()
    check(TAG in PARAMS, 'run the N or O model-local test copy')
    result = load_current()
    report = dict(status='PASS_NATIVE_IDLE_RETRY_M2', model=TAG,
                  image_sha256=digest(result['image']), cases=verify(result),
                  native_entry=PARAMS[TAG], hardware_accessed=False,
                  helper_replacements=0, boot_verified=False,
                  boundaries=['Static explicit SFR inputs; no interrupt or physical timing simulation.',
                              'O TTL/DEF executes original service 75AC; pending plan is held by native gate.',
                              'Native encoded expiry clock/count policy is unchanged.'],
                  source_sha256={str(p.relative_to(HERE.parent)):digest(p.read_bytes()) for p in
                      (Path(__file__), HERE / 'native_hooks.py', SHARED / 'runtime_generator.py',
                       SHARED / 'test_integrated_firmware.py', SHARED / 'pic18_vm.py')})
    if args.baseline_directory:
        baseline = load_frozen(args.baseline_directory)
        report['frozen_m1'] = dict(image_sha256=digest(baseline['image']),
                                   counterexamples=frozen_counterexamples(baseline))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], model=TAG, cases=len(report['cases']),
                         frozen_counterexamples=len(report.get('frozen_m1', {}).get('counterexamples', []))),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
