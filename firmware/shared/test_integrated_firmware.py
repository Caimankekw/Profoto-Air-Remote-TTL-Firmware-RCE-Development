#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Independent bounded tests of linked stock + AIR2 PIC18 machine code.

The linker can call verify_model() directly with the exact in-memory image.
This module does not build installers, open hardware, or replace core/native
functions with success stubs. MMIO and the downstream queue-consumer boundary
are explicit models and are reported separately from executed native code.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

from pic18_vm import CPU

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STATE = 0x680


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def section_bytes(section):
    data = section.get('data')
    if isinstance(data, dict):
        return bytes.fromhex(data['hex'])
    if data is not None:
        return bytes(data)
    return bytes.fromhex(section['data_hex'])


def hook_bytes(hook):
    return bytes.fromhex(hook.get('new_hex', hook.get('replacement_hex', '')))


def link_for_replay(tag, profile, persistence_proof, code_base=None):
    """Construct only an in-memory linked image for independent tests.

    Call in a fresh process per model: model modules intentionally use local
    import names. The production linker remains independently responsible for
    qualifications, immutable manifests and packaging.
    """
    tagdir = ROOT/tag
    for name in ('native_backend', 'native_hooks', 'model_adapter', 'native_contract'):
        old = sys.modules.get(name)
        if old is not None and Path(old.__file__).resolve().parent != tagdir.resolve():
            raise RuntimeError('use a fresh process for each model; imported '+name)
    sys.path.insert(0, str(tagdir))
    stock_dir = HERE/'stock'/tag
    original = (stock_dir/'original.base4000.partial.bin').read_bytes()
    mask = (stock_dir/'original.known_mask.bin').read_bytes()
    stock_profile = json.loads((stock_dir/'profile.json').read_text())
    check(digest(original) == stock_profile['partial_plaintext_sha256'], 'stock source hash')
    if code_base is None:
        code_base = (stock_profile['last_non_ff_end_exclusive_below_10000']+3) & ~3
    source_paths = sorted({*HERE.glob('*.py'), *tagdir.rglob('*.py')})
    before = {str(p):digest(p.read_bytes()) for p in source_paths}
    if (tagdir/'model_adapter.py').exists():
        adapter = importlib.import_module('model_adapter')
        result = adapter.construct(original, profile=profile,
                                   persistence_proof=persistence_proof, code_base=code_base)
        components = result['components']
        hooks = result['hooks']
        sections = result['sections']
    else:
        runtime = importlib.import_module('runtime_generator')
        persistence = importlib.import_module('persistence_backend')
        native = importlib.import_module('native_backend')
        hookmod = importlib.import_module('native_hooks')
        def end(component):
            return max(s['address']+len(s['data']) for s in component['sections'])
        c0 = runtime.construct(original, code_base=code_base, profile=profile,
                               backend={name:0x4000 for name in runtime.required_imports(profile)})
        kw = dict(code_base=end(c0), profile=profile, imports=c0['exports'])
        if 'state_base' in inspect.signature(native.construct).parameters:
            kw['state_base'] = profile['state_base']
        backend = native.construct(original, **kw)
        nv = persistence.construct(original, code_base=end(backend), profile=profile,
              backend={'persistence':persistence_proof},
              imports={'read_inputs':backend['exports']['read_inputs']})
        core = runtime.construct(original, code_base=code_base, profile=profile,
                                 backend={**backend['exports'], **nv['exports']})
        check(core['exports'] == c0['exports'] and end(core) == end(c0), 'two-pass core moved')
        hsig = inspect.signature(hookmod.construct).parameters
        hk = dict(code_base=end(nv), profile=profile)
        if 'core' in hsig:
            hk['core'], hk['backend'] = core['exports'], backend['exports']
        else:
            hk['imports'] = {**core['exports'], **backend['exports']}
        if 'backend_exports' in hsig:
            hk['backend_exports'] = backend['exports']
        if 'state_base' in hsig:
            hk['state_base'] = profile['state_base']
        h = hookmod.construct(original, **hk)
        components = dict(core=core, backend=backend, persistence=nv, hooks=h)
        sections = [s for component in components.values() for s in component['sections']]
        hooks = h['hooks']
    image = bytearray(original)
    occupied = set()
    for section in sections:
        address, data = section['address'], bytes(section['data'])
        offset = address-0x4000
        check(address >= code_base and address+len(data) <= profile['code_limit'], 'code allocation')
        check(original[offset:offset+len(data)] == b'\xff'*len(data)
              and all(mask[offset:offset+len(data)]), 'nonempty/unknown code cave')
        span = set(range(offset, offset+len(data)))
        check(not occupied & span, 'component code overlap')
        occupied.update(span)
        image[offset:offset+len(data)] = data
    for hook in hooks:
        offset = hook['address']-0x4000
        expected, data = bytes.fromhex(hook['expected_hex']), hook_bytes(hook)
        check(original[offset:offset+len(expected)] == expected and len(expected) == len(data), 'hook preimage/length')
        span = set(range(offset, offset+len(data)))
        check(not occupied & span, 'hook overlap')
        occupied.update(span)
        image[offset:offset+len(data)] = data
    for p in source_paths:
        check(before[str(p)] == digest(p.read_bytes()), 'source changed while linking: '+str(p))
    return dict(tag=tag, image=bytes(image), mask=mask, profile=profile,
                components=components, hooks=hooks, source_paths=source_paths)


MODEL = {
    'N': {
        'mode': 0x1B1, 'head': 0x4C, 'model': 0x50, 'fec': 0x1B5, 'selector': 0x60,
        'tick': 0x11B, 'secondary': (0x282, 0x286, 0x28A),
        'descriptor': 0x93, 'ring': 0x400,
        'defaults': {0x49: 0xB1, 0x4A: 1, 0x60: 7, 0x47: 3, 0x48: 0},
        'power_hook': (0x7E0A, 0x7E10), 'press_hook': (0x55EC, 0x55F0),
        'press_pointer': (0xC0, 0xC1), 'select_a_object': 0x27A,
        'busy_input': 0x4D,
    },
    'O': {
        'mode': 0x199, 'head': 0x2C, 'model': 0x3F, 'fec': 0x19D, 'selector': 0x60,
        'tick': 0x75, 'secondary': (0x114, 0x118, 0x11C),
        'descriptor': 0x95, 'ring': 0x300,
        'defaults': {0x7E: 0x99, 0x7F: 1, 0x60: 7, 0x24: 3, 0x40: 1},
        'power_hook': (0x86D6, 0x86DA), 'press_hook': (0x5C12, 0x5C16),
        'press_pointer': (0xF2, 0xF3), 'select_a_object': 0x10C,
        'busy_input': 0x82,
    },
    'F': {
        'mode': 0x18C, 'head': 0x29, 'model': 0x38, 'fec': 0x190, 'selector': 0x60,
        'tick': 0x106, 'secondary': (0x11E, 0x122, 0x126),
        'descriptor': 0x92, 'ring': 0x500,
        'defaults': {0x22: 0x8C, 0x23: 1, 0x60: 7, 0x3A: 1,
                     0xFA4: 0, 0xFF0: 0},
        'power_hook': (0x8D7E, 0x8D84), 'press_hook': (0x5E6A, 0x5E6E),
        'press_pointer': (0xEA, 0xEB), 'select_a_object': 0x116,
        'busy_input': 0x7A,
    },
    'S': {
        'mode': 0x193, 'head': 0xDB, 'model': 0xF3, 'fec': 0x197, 'selector': 0xC1,
        'tick': 0x106, 'secondary': (0x125, 0x129, 0x12D),
        'descriptor': 0xE6, 'ring': 0x400,
        'defaults': {0xD2: 0x93, 0xD3: 1, 0xC1: 7, 0xD0: 3, 0xD1: 0,
                     0x56: 1, 0xFD0: 0x80, 0xFF0: 0, 0xF98: 0, 0xFA4: 0},
        'power_hook': (0x87CC, 0x87D2), 'press_hook': (0x8116, 0x595A),
        'press_pointer': (0xAB, 0xAC), 'select_a_object': 0x11D,
        'busy_input': 0xDD,
    },
}


class FlashBoundary:
    """Only the memory effect of the declared 47J13/J53 controller is supplied.

    Unlock, bounds, IRQ masking, pointer selection, CRC and readback must come
    from executed machine code. This is not an electrical atomicity proof.
    """
    def __init__(self, cpu, fail_word=None):
        self.cpu = cpu
        self.unlock = []
        self.operations = []
        self.fail_word = fail_word
        self.word_count = 0
        cpu.write_hooks[0xFA7] = self.key
        cpu.write_hooks[0xFA6] = self.control

    def key(self, cpu, value):
        cpu.m[0xFA7] = value
        self.unlock = (self.unlock + [value])[-2:]

    def control(self, cpu, value):
        cpu.m[0xFA6] = value
        if not value & 2:
            return
        check(self.unlock == [0x55, 0xAA], 'Flash unlock sequence')
        check(value & 4, 'Flash write enable')
        check(not cpu.m[0xFF2] & 0xC0, 'Flash command with enabled interrupts')
        self.unlock.clear()
        pointer = cpu.tblptr()
        if value & 0x10:
            check(not value & 0x20 and pointer in (0xF800, 0xFC00), 'Flash erase outside owned pages')
            cpu.flash[pointer:pointer+0x400] = b'\xff' * 0x400
            self.operations.append(('erase', pointer))
        else:
            start = pointer & ~1
            check(value & 0x20 and pointer == start+1 and 0xF800 <= start <= 0xFFFE, 'Flash word geometry')
            check(start in cpu.latches and start+1 in cpu.latches, 'Flash word latch completeness')
            self.word_count += 1
            if self.word_count != self.fail_word:
                for i in range(2):
                    cpu.flash[start+i] &= cpu.latches[start+i]
            else:
                cpu.m[0xFA6] |= 8
            self.operations.append(('word', start))
        cpu.latches.clear()
        cpu.m[0xFA6] &= ~2


class Machine:
    def __init__(self, tag, image, mask, profile, components, *, mode=1,
                 flash=None, native_values=None, fail_word=None):
        check(tag in MODEL, 'native input contract not yet installed for ' + tag)
        self.tag, self.profile, self.components = tag, profile, components
        self.contract = MODEL[tag]
        self.base = int(profile['state_base'])
        values = {0xFA6: 0, 0xFA7: 0, 0xFF2: 0xC0}
        values.update(self.contract['defaults'])
        values.update({int(a, 0) if isinstance(a, str) else int(a): int(v)
                       for a, v in profile.get('vm_idle_sfr', {}).items()})
        values.update({self.contract['mode']: mode,
                       self.contract['head']: 7, self.contract['model']: 0})
        values.update(native_values or {})
        flash_mask = None
        if flash is not None:
            flash_mask = bytearray(len(flash))
            flash_mask[0x4000:0x4000+len(mask)] = mask
        self.cpu = CPU(image, values, mask=mask, flash=flash, flash_mask=flash_mask,
                       max_steps=2000000)
        self.flash = FlashBoundary(self.cpu, fail_word=fail_word)
        d, buf = self.contract['descriptor'], self.contract['ring']
        self.cpu.m[d:d+6] = bytes((0, 0, 0, 100, buf & 255, buf >> 8))
        self.frames = []
        self.queue_boundary_events = []

    def export(self, group, name):
        component = self.components[group]
        check(name in component['exports'], 'missing %s export %s' % (group, name))
        return component['exports'][name]

    def call(self, name, w=None, group='core', **kwargs):
        if w is not None:
            self.cpu.w = w
        self.cpu.run(self.export(group, name), **kwargs)
        check(not any(e[0] == 'step_hook' for e in self.cpu.events), 'helper was replaced')
        return self.cpu.w

    def state(self, offset, count=1):
        values = self.cpu.m[self.base+offset:self.base+offset+count]
        return values[0] if count == 1 else bytes(values)

    def set_state(self, offset, values):
        if isinstance(values, int):
            self.cpu.m[self.base+offset] = values
        else:
            self.cpu.m[self.base+offset:self.base+offset+len(values)] = values

    def tick(self, value):
        address = self.contract['tick']
        self.cpu.m[address:address+2] = (value & self.profile['clock_mask']).to_bytes(2, 'little')

    def secondary(self, bits):
        for i, address in enumerate(self.contract['secondary']):
            self.cpu.m[address] = (self.cpu.m[address] & 0xFE) | ((bits >> i) & 1)

    def consume_queued_packet(self):
        """Explicit downstream consumer boundary; native enqueue was executed.

        Does not claim execution of the native asynchronous scheduler or RF ACK.
        The full 17-byte marker+body is read and validated before advancing it.
        """
        d, buf = self.contract['descriptor'], self.contract['ring']
        count = self.cpu.m[d+2]
        if not count:
            return None
        check(count == 17, 'expected one complete admitted 17-byte packet, got %d' % count)
        read = self.cpu.m[d+1]
        data = bytes(self.cpu.m[buf+(read+i) % 100] for i in range(17))
        check(data[0] == 0, 'native radio marker')
        self.cpu.m[d+1] = (read+17) % 100
        self.cpu.m[d+2] = 0
        self.frames.append(data[1:])
        self.queue_boundary_events.append({'descriptor': d, 'packet_hex': data.hex()})
        return data[1:]

    def service_until_idle(self, limit=30):
        for step in range(limit):
            self.consume_queued_packet()
            current = int.from_bytes(self.cpu.m[self.contract['tick']:self.contract['tick']+2], 'little')
            self.tick(current+1)
            self.call('service')
            self.consume_queued_packet()
            if not self.state(0x28):
                return
        raise AssertionError('transaction did not finish within bounded service calls')


def frame(command, group=None, data=()):
    if command in (0x11, 0x25):
        return bytes((0x27, 255, 255, 255, 1, command, *data)) + bytes(10-len(data))
    return bytes((group, 255, 255, 255, 1, command, group)) + bytes(9)


def verify_model(tag, image, mask, profile, components, hooks=(), source_paths=()):
    """Public linker integration API. Inputs are the actual linked bytes.

    components must provide core/backend/persistence dictionaries with exports.
    Reports incomplete coverage honestly; success is only for executed cases.
    """
    image, mask = bytes(image), bytes(mask)
    check(len(image) == len(mask), 'linked mask length')
    check(profile.get('model_tag') == tag, 'profile tag')
    check(int(profile['state_base']) == STATE, 'this test contract expects state680')
    stock_path = HERE/'stock'/tag
    stock_profile_bytes = (stock_path/'profile.json').read_bytes()
    stock_profile = json.loads(stock_profile_bytes)
    original = (stock_path/'original.base4000.partial.bin').read_bytes()
    stock_mask = (stock_path/'original.known_mask.bin').read_bytes()
    check(digest(original) == stock_profile['partial_plaintext_sha256'], 'stock plaintext binding')
    check(digest(stock_mask) == stock_profile['known_mask_sha256'] and mask == stock_mask,
          'stock known-mask binding')
    check(len(image) == len(original) == stock_profile['end_exclusive']-0x4000,
          'linked image length differs from original program span')
    before_hashes = {str(p): digest(Path(p).read_bytes()) for p in source_paths}
    counts = {}
    observations = []

    def passed(name):
        counts[name] = counts.get(name, 0) + 1

    def new(mode=1, flash=None, values=None, fail_word=None):
        return Machine(tag, image, mask, profile, components, mode=mode,
                       flash=flash, native_values=values, fail_word=fail_word)

    # Random retained RAM cannot authorize projection before initialization.
    for mode in (0, 1):
        m = new(mode)
        m.set_state(0x17, 2)
        m.cpu.track_trace = True
        m.call('service')
        check(m.export('backend', 'apply_native_state') not in m.cpu.trace
              and not m.flash.operations and m.cpu.m[m.contract['descriptor']+2] == 0,
              'uninitialized boot-pending bit authorized native mutation')
        passed('invalid_magic_pending_no_projection')

    # Stop immediately before the first real backend call. The optimized
    # initializer must clear exactly its own 00..AF, preserving saved caller
    # context in provider B0..17F before a backend is allowed to use that area.
    m = new()
    m.cpu.m[m.base:m.base+0x180] = bytes((i*17+3) & 255 for i in range(0x180))
    provider = bytes(m.cpu.m[m.base+0xB0:m.base+0x180])
    m.cpu.run(m.export('core', 'init'), stops=(m.export('backend', 'read_inputs'),))
    check(not any(m.cpu.m[m.base:m.base+0xB0]) and bytes(m.cpu.m[m.base+0xB0:m.base+0x180]) == provider,
          'init clear loop touched provider context or missed core bytes')
    passed('init_prefix_provider_canary')

    # Native snapshot + canonical initializer must not enqueue or program Flash.
    for mode in (0, 1):
        m = new(mode)
        m.call('init')
        check(m.state(0) == 0xA8 and m.state(1) == mode, 'initializer/mode projection')
        check(m.state(2) == 1 and m.state(8, 6) == bytes((50,)*6), 'initializer defaults')
        check(m.cpu.m[m.contract['descriptor']+2] == 0 and not m.flash.operations,
              'boot produced radio or Flash writes')
        check(m.state(0x77) & 0x80, 'real read_inputs snapshot invalid')
        passed('init_real_native_snapshot')
        for row in (1, 2, 3):
            m.call('display_row', row)
            check(m.cpu.w == (1 if mode == 0 else 0) and m.state(0x61) == 0,
                  'initial FEC/hidden relative display differs')
            passed('display_row')
        m.call('redraw', group='backend')
        passed('native_redraw')

    # Validate the canonical formatter ABI's value as well as type for every
    # row/domain. Native glyph/LCD electrical output remains a separate test.
    for mode in (0, 1):
        for manual in (1, 2):
            for page in (0, 1):
                m = new(mode); m.call('init')
                m.set_state(2, manual); m.set_state(3, page)
                m.set_state(5, 63); m.set_state(7, 63)
                targets = bytes((1, 10, 25, 50, 75, 100))
                relative = bytes((157, 246, 255, 1, 10, 99))
                fec = bytes((236, 0, 20))
                m.set_state(8, targets); m.set_state(0x0E, relative); m.set_state(0x14, fec)
                for row in (1, 2, 3):
                    g = page*3+row-1
                    if mode == 0 and page == 0:
                        expected_kind, expected_value = 1, fec[row-1]
                    elif manual == 2:
                        expected_kind, expected_value = 2, targets[g]
                    else:
                        expected_kind, expected_value = 1, relative[g]
                    check(m.call('display_row', row) == expected_kind
                          and m.state(0x61) == expected_value, 'canonical display domain/value mismatch')
                    passed('display_exact_domain_value')
    for g in range(6):
        m = new(); m.call('init'); m.set_state(2, 2); m.set_state(3, g//3)
        m.set_state(5, 63 ^ (1 << g))
        check(m.call('display_row', g%3+1) == 3 and m.state(0x61) == 0,
              'head OFF row not represented by OFF display kind')
        passed('display_head_off')

    # Canonical states are deliberately set at entry to isolate each power path.
    # The operation, snapshot, projection and frame emission remain machine code.
    for mode, manual, page, selector, step in (
            (1, 2, 0, 1, 1), (1, 2, 1, 2, -1), (1, 2, 1, 7, 10),
            (1, 1, 1, 1, 1), (1, 1, 1, 7, -10),
            (0, 1, 0, 1, 1), (0, 1, 1, 2, -1),
            (0, 1, 1, 7, 1), (0, 2, 1, 7, 1)):
        m = new(mode)
        m.call('init')
        for offset, value in ((2, manual), (3, page), (4, selector), (5, 63), (6, 0)):
            m.set_state(offset, value)
        m.cpu.m[m.contract['selector']] = selector
        before = m.state(8, 15)
        accepted = m.call('power_edit', step & 255)
        check(accepted == 1, 'power edit refused %s' % ((mode, manual, page, selector, step),))
        m.service_until_idle()
        check(m.frames, 'accepted edit had no complete native frame')
        physical = 3*page + selector if selector != 7 else None
        expected = []
        if mode == 0 and (page == 0 or selector == 7):
            fec = [0, 0, 0]
            if selector == 7:
                fec = [step]*3
            else:
                fec[selector-1] = step
            expected.append(frame(0x25, data=[v & 255 for v in fec]))
        manual_groups = list(range(1, 7)) if mode == 1 and selector == 7 else list(range(4, 7)) if mode == 0 and selector == 7 else [physical] if mode == 1 or page == 1 else []
        if manual_groups:
            if manual == 2:
                targets = [50]*6
                for g in manual_groups:
                    targets[g-1] += step
                expected.append(frame(0x11, data=[*targets, 63, 0]))
            else:
                command = {1: 6, -1: 7, 10: 13, -10: 14}[step]
                expected.extend(frame(command, group=g) for g in manual_groups)
        check(m.frames == expected, 'native frame sequence mismatch %s: %s != %s' % (
            (mode, manual, page, selector, step), [x.hex() for x in m.frames], [x.hex() for x in expected]))
        check(m.state(8, 15) != before, 'edit produced no canonical change')
        passed('power_native_queue_sequence')

    # Native selection projection must agree with the canonical selection,
    # including the original same-group -> ALL convention.
    for row in (1, 2, 3):
        m = new()
        m.call('init')
        check(m.call('select_row', row) == 1 and m.state(4) == row,
              'select row failed')
        check(m.cpu.m[m.contract['selector']] == row, 'selector native projection')
        check(m.call('select_row', row) == 1 and m.state(4) == 7,
              'same row did not toggle ALL')
        check(m.cpu.m[m.contract['selector']] == 7, 'ALL native projection')
        check(not m.frames and m.cpu.m[m.contract['descriptor']+2] == 0,
              'selection emitted an RF command')
        passed('same_row_toggle_all')

    # Exercise the actual deferred gesture code through sampled native objects.
    for raw, target_offset, target_value in ((3, 2, 2), (5, 3, 1)):
        m = new()
        m.call('init')
        m.secondary(1); m.tick(0)
        check(m.call('secondary_press', 1) == 1, 'C chord start refused')
        m.secondary(raw); m.tick(5); m.call('service')
        m.tick(5+profile['stable_counts']); m.call('service')
        check(m.state(target_offset) == target_value, 'chord action missing')
        canonical = m.state(1, 7)
        for tick in (30, 100, 250):
            m.tick(tick); m.call('service')
            check(m.state(1, 7) == canonical, 'held chord repeated/leaked a constituent')
        m.secondary(0); m.tick(300); m.call('service')
        m.tick(300+profile['stable_counts']); m.call('service')
        check(m.state(0x18) == 0 and not m.frames
              and m.cpu.m[m.contract['descriptor']+2] == 0, 'chord release/radio isolation')
        passed('native_secondary_chord_hold_release')

    # Model state can be ignored by receivers while their head is off. The
    # complete machine-code path must reassert both ON and OFF intent on head
    # re-enable, including an ALL-six transaction and a group on the DEF page.
    for page, selector, initially_on in ((0, 1, False), (1, 2, True), (1, 7, False)):
        m = new(); m.call('init')
        m.set_state(3, page); m.set_state(4, selector); m.set_state(5, 63)
        m.set_state(6, 63 if initially_on else 0)
        m.cpu.m[m.contract['selector']] = selector
        m.cpu.m[m.contract['model']] = 7 if initially_on else 0
        groups = list(range(1, 7)) if selector == 7 else [page*3+selector]
        def single(key):
            now = int.from_bytes(m.cpu.m[m.contract['tick']:m.contract['tick']+2], 'little')
            m.secondary(0)
            check(m.call('secondary_press', key) == 1, 'released secondary refused')
            m.tick(now+profile['stable_counts'])
            m.call('service'); m.service_until_idle()
            check(m.state(0x18) == 0, 'released secondary remained latched')
        single(4)  # HEAD OFF
        single(2)  # MODEL changes while HEAD OFF
        single(4)  # HEAD ON then canonical MODEL reasserted
        model_cmd = 3 if initially_on else 2
        expected = ([frame(1, group=g) for g in groups]
                    + [frame(model_cmd, group=g) for g in groups]
                    + [f for g in groups for f in (frame(0, group=g), frame(model_cmd, group=g))])
        check(m.frames == expected, 'head/model cache reassertion frame mismatch')
        passed('head_off_model_change_head_on_reassertion')

    # A nonsecondary power edit does not wait for the gesture deadline.
    for step in (1, 10, 10):
        m = new()
        m.call('init'); m.set_state(2, 2)
        check(m.call('power_edit', step) == 1 and m.state(0x18) == 0,
              'power edit incorrectly entered secondary wait')
        m.service_until_idle()
        passed('power_short_long_no_chord_delay')

    # Test externally completed native TTL/MAN transitions. The native owner
    # supplies the changed mode; service reconciles state without mode RF.
    for manual in (1, 2):
        m = new()
        m.call('init'); m.set_state(2, manual)
        targets = bytes((11, 22, 33, 44, 55, 66))
        m.set_state(8, targets)
        m.cpu.m[m.contract['fec']:m.contract['fec']+3] = bytes((236, 0, 20))
        for mode in (0, 1, 0, 1):
            m.cpu.m[m.contract['mode']] = mode
            m.call('service')
            check(m.state(1) == mode and m.state(2) == manual,
                  'native mode transition lost manual subtype')
            check(m.state(8, 6) == targets and m.state(0x14, 3) == bytes((236, 0, 20)),
                  'native mode transition mixed FEC/absolute cache')
            check(m.cpu.m[m.contract['descriptor']+2] == 0, 'mode sync emitted command')
        passed('mode_memory_and_bank_separation')

    for mode, manual, max_offset in ((1, 2, 8), (0, 2, 0x14)):
        m = new(mode)
        m.call('init'); m.set_state(2, manual); m.set_state(5, 63)
        m.set_state(max_offset, 100 if mode else 20)
        if mode == 0:
            m.cpu.m[m.contract['fec']] = 20
        before = m.state(8, 15)
        check(m.call('power_edit', 1) == 0, 'out-of-range ALL edit accepted')
        check(m.state(8, 15) == before and m.state(0x28) == 0,
              'out-of-range ALL edit partially changed state')
        passed('atomic_all_preflight')

    pending = []
    if hooks and 'hooks' in components and 'power_hook' in MODEL[tag]:
        covered = set()
        for component in components.values():
            for section in component.get('sections', ()):
                start = section['address']-0x4000
                data = section_bytes(section)
                length = len(data)
                span = set(range(start, start+length))
                check(section['address'] >= stock_profile['last_non_ff_end_exclusive_below_10000']
                      and section['address']+length <= profile['code_limit']
                      and not covered & span, 'section allocation/overlap')
                check(original[start:start+length] == b'\xff'*length
                      and all(mask[start:start+length]), 'section does not occupy known empty code')
                check(image[start:start+length] == data, 'linked section bytes mismatch')
                covered.update(span)
        for hook in hooks:
            start = hook['address']-0x4000
            expected, replacement = bytes.fromhex(hook['expected_hex']), hook_bytes(hook)
            span = set(range(start, start+len(replacement)))
            check(expected and len(expected) == len(replacement) and not covered & span,
                  'hook width/overlap')
            check(original[start:start+len(expected)] == expected, 'hook preimage mismatch')
            check(image[start:start+len(replacement)] == replacement, 'linked hook mismatch')
            covered.update(span)
        check(all(a == b or i in covered for i, (a, b) in enumerate(zip(original, image))),
              'unexpected stock byte changed outside code sections/hooks')
        check(image[2:0x100] == original[2:0x100], 'stock header/HSS calibration prefix changed')
        passed('stock_preservation_except_declared_ui_hooks')

        hc = components['hooks']
        contexts = (hc.get('metadata', {}).get('context_addresses')
                    or hc.get('metadata', {}).get('context_registers')
                    or components['backend'].get('metadata', {}).get('context_saved_addresses'))
        check(contexts, 'hook context contract missing')
        minimum_cpu_context = {0xFE8, 0xFD8, 0xFE0, 0xFE9, 0xFEA,
                               0xFE1, 0xFE2, 0xFD9, 0xFDA, 0xFF3, 0xFF4,
                               0xFF5, 0xFF6, 0xFF7, 0xFF8}
        check(minimum_cpu_context <= set(contexts), 'hook omitted required core CPU register context')
        entry, continuation = MODEL[tag]['power_hook']
        for step in (1, 10, 246):
            m = new(); m.call('init'); m.set_state(2, 2)
            for address in contexts:
                value = (address*13+7) & 255
                if address in (0xFE0, 0xFEA, 0xFE2, 0xFDA): value &= 15
                if address in (0xFD8, 0xFFB): value &= 31
                if address == 0xFF8: value &= 63
                m.cpu.m[address] = value
            m.cpu.m[0xFE0] = 0
            m.cpu.w = step
            expected = {address:m.cpu.m[address] for address in contexts}
            m.cpu.track_trace = True
            m.cpu.run(entry)
            check(all(m.cpu.m[a] == v for a,v in expected.items()),
                  'native power wrapper corrupted caller context: '+str([(hex(a),v,m.cpu.m[a]) for a,v in expected.items() if m.cpu.m[a]!=v]))
            delta = step if step < 128 else step-256
            check(m.state(8, 3) == bytes((50+delta,)*3), 'patched native short/hold power did not edit')
            check(continuation not in m.cpu.trace and not m.cpu.stack,
                  'handled native key fell into original relative path')
            passed('actual_power_hook_context_and_no_legacy_duplicate')
        # Uninitialized execution must reproduce the exact displaced prefix,
        # without executing any core entry before the original continuation.
        m = new(); m.cpu.w = 1; m.cpu.track_trace = True
        m.cpu.run(entry, stops=(continuation,))
        check(m.cpu.pc == continuation and not any(x in m.cpu.trace for x in components['core']['exports'].values()),
              'uninitialized native power did not fall back')
        passed('uninitialized_legacy_prefix_fallback')
        m = new(); m.call('init')
        a, b = MODEL[tag]['press_pointer']; obj = MODEL[tag]['select_a_object']
        m.cpu.m[a],m.cpu.m[b] = obj & 255,obj >> 8
        m.cpu.run(MODEL[tag]['press_hook'][0])
        check(m.state(4) == 1 and m.cpu.m[m.contract['selector']] == 1,
              'native A callback did not project selected row')
        passed('actual_native_group_callback')
        observations.append('All stock bytes outside the declared UI hooks and new code sections were compared. Original HSS phase execution is not claimed by this byte-preservation check.')
    else:
        pending.append('outer native hooks/context/legacy fallback and stock preservation')
    if profile.get('nv_enabled', False):
        m = new()
        m.call('init'); m.set_state(2, 2); m.set_state(3, 1)
        m.set_state(5, 63); m.set_state(6, 0x2A)
        m.cpu.m[m.contract['model']] = 0x2A & 7
        check(m.call('power_edit', 1) == 1, 'persistent edit refused')
        m.service_until_idle()
        m.call('service')
        check(m.flash.operations and m.state(0x17) == 0,
              'real native readiness/persistence path did not durably save')
        saved = {i: m.state(i) for i in (1, 2, 3, 5, 6, *range(8, 14))}
        reboot = new(mode=0, flash=bytes(m.cpu.flash))
        reboot.call('init')
        check(all(reboot.state(i) == value for i, value in saved.items()),
              'save/reboot canonical state mismatch')
        check(reboot.cpu.m[reboot.contract['mode']] == saved[1],
              'reboot native mode not projected')
        check(not reboot.flash.operations and reboot.cpu.m[reboot.contract['descriptor']+2] == 0,
              'reboot wrote NVM or queued radio')
        passed('real_nv_commit_restart_projection')

        for external_mode_change in (False, True):
            busy_address = MODEL[tag]['busy_input']
            blocked = new(mode=0, flash=bytes(m.cpu.flash), values={busy_address:1})
            blocked.call('init')
            check(blocked.state(0x17) & 2 and blocked.state(1) == saved[1]
                  and blocked.cpu.m[blocked.contract['mode']] == 0,
                  'busy boot must retain pending saved mode without forced projection')
            for _ in range(2):
                blocked.call('service')
            check(not blocked.flash.operations
                  and blocked.cpu.m[blocked.contract['descriptor']+2] == 0,
                  'pending boot emitted RF or saved an unprojected mode')
            blocked.cpu.m[busy_address] = 0
            if external_mode_change:
                blocked.cpu.m[blocked.contract['mode']] = 1
            blocked.cpu.track_trace = True
            blocked.cpu.trace.clear()
            blocked.call('service')
            check(not blocked.state(0x17) & 2
                  and blocked.cpu.m[blocked.contract['mode']] == 1,
                  'boot pending did not resolve')
            calls = blocked.cpu.trace.count(blocked.export('backend','apply_native_state'))
            check(calls == 1,
                  'boot pending did not retry its fresh-gated projection')
            check(blocked.state(5) == saved[5] and blocked.state(6) == saved[6]
                  and blocked.cpu.m[blocked.contract['head']] & 7 == saved[5] & 7
                  and blocked.cpu.m[blocked.contract['model']] & 7 == saved[6] & 7,
                  'boot pending lost saved Head/Model while accepting native mode')
            passed('boot_pending_camera_masks_restore' if external_mode_change else 'boot_pending_ready_retry')

        durable_sequence = int.from_bytes(reboot.cpu.flash[0xF804:0xF806], 'little')
        check(int.from_bytes(reboot.state(0x2E, 2), 'little') == durable_sequence,
              'boot sequence differs from durable record')
        check(reboot.call('power_edit', 1) == 1, 'second persistent edit refused')
        reboot.service_until_idle(); reboot.call('service')
        second = int.from_bytes(reboot.cpu.flash[0xF824:0xF826], 'little')
        check(second == (durable_sequence+1) & 0xFFFF
              and int.from_bytes(reboot.state(0x2E, 2), 'little') == second,
              'next save sequence did not follow actual durable sequence')
        passed('nv_sequence_after_restart')
        failed = new(fail_word=1)
        failed.call('init'); failed.set_state(2, 2)
        check(failed.call('power_edit', 1) == 1, 'failed-save edit refused early')
        failed.service_until_idle(); failed.call('service')
        check(failed.state(0x17) & 0x80, 'NVM failure did not latch')
        writes = list(failed.flash.operations)
        for _ in range(3): failed.call('service')
        check(failed.flash.operations == writes, 'faulted journal was retried automatically')
        passed('nv_fault_latch_no_repeat')
    else:
        pending.append('NVM disabled by supplied profile; save/reboot not tested')

    for p in source_paths:
        check(digest(Path(p).read_bytes()) == before_hashes[str(p)], 'source changed during replay: '+str(p))
    return {
        'status': 'PASS_BOUNDED_LINKED_CASES', 'model': tag,
        'image_sha256': digest(image), 'known_mask_sha256': digest(mask),
        'stock_plaintext_sha256':digest(original),
        'stock_profile_sha256':digest(stock_profile_bytes),
        'profile': profile, 'source_sha256': before_hashes,
        'vm_sha256': digest((HERE/'pic18_vm.py').read_bytes()),
        'test_sha256': digest(Path(__file__).read_bytes()),
        'cases_passed': sum(counts.values()), 'cases': counts,
        'observations': observations,
        'native_function_replacements': 0,
        'external_models': ['explicit static native idle SFR inputs from fixture/profile',
                            'explicit Flash SFR memory-effect model',
                            'downstream native queue consumer between service calls'],
        'scope_limits':['Full integration means all listed bounded cases passed, not full state-space or hardware validation.',
                        'Display query types/values are checked; real native redraw executes without substituted helpers. Pixel correctness is additionally covered by model-specific glyph/LCD tests.',
                        'Caller scratch coverage depends on model-reviewed context metadata; a fixed minimum CPU register set is independently enforced.',
                        'The test begins at reviewed initialized native-state boundaries, not from a complete physical reset/bootloader execution.'],
        'coverage_pending': pending,
        'hardware_accessed': False, 'updater_executed': False,
        'full_integration_pass': not pending,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--manifest', type=Path,
                        help='Linker JSON: model_tag, image_path, mask_path, profile, components, hooks')
    sources.add_argument('--link-model', choices=tuple(MODEL),
                         help='Link a formal local profile in memory only, then replay')
    sources.add_argument('--all-models', action='store_true',
                         help='Replay each formal model in a fresh Python subprocess')
    parser.add_argument('--out', type=Path,
                        help='Optional JSON output; no firmware/installer is emitted')
    args = parser.parse_args()
    if args.all_models:
        models = {}
        for tag in MODEL:
            command = [sys.executable]
            if sys.flags.optimize:
                command.append('-O')
            command += [str(Path(__file__).resolve()), '--link-model', tag]
            run = subprocess.run(command, check=True, capture_output=True, text=True)
            models[tag] = json.loads(run.stdout)
            check(models[tag]['full_integration_pass'], 'bounded coverage incomplete: '+tag)
        result = {'status':'PASS_BOUNDED_FOUR_MODEL_INTEGRATION', 'models':models,
                  'cases_passed':sum(x['cases_passed'] for x in models.values()),
                  'python_optimization':sys.flags.optimize,
                  'hardware_accessed':False, 'updater_executed':False,
                  'firmware_artifacts_written':False}
    elif args.link_model:
        import build_variants
        tag = args.link_model
        path = ROOT/tag/'port_profile.json'
        profile = json.loads(path.read_text(encoding='utf-8'))
        linked = build_variants.link(tag, profile)
        paths = [HERE/name for name in ('runtime_generator.py','gesture_runtime_codegen.py',
                                        'record_runtime_codegen.py','persistence_backend.py')]
        paths += sorted(p for p in (ROOT/tag).rglob('*.py') if not p.name.startswith('test_'))
        result = verify_model(tag, linked['image'], linked['mask'], profile,
                              linked['components'], linked['plan']['hooks'], paths)
        result['code_end'] = linked['code_end']
        result['profile_file_sha256'] = digest(path.read_bytes())
        result['linker_sha256'] = digest((HERE/'build_variants.py').read_bytes())
    else:
        spec = json.loads(args.manifest.read_text(encoding='utf-8'))
        def local(path):
            p = Path(path)
            return p if p.is_absolute() else args.manifest.parent/p
        image = local(spec['image_path']).read_bytes()
        mask = local(spec['mask_path']).read_bytes()
        result = verify_model(spec['model_tag'], image, mask, spec['profile'], spec['components'],
                              spec.get('hooks', ()), [local(p) for p in spec.get('source_paths', ())])
        result['manifest_sha256'] = digest(args.manifest.read_bytes())
    if args.out is not None:
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
