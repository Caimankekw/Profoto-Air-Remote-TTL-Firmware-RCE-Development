#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Execute state wrappers plus original Sony pure UI helpers.

The ABI matrix stubs quiet imports explicitly. Atomic projection tests execute
the reviewed pure Sony quiet predicate and schedule a camera mode-change event
at each instruction boundary. This is not a physical IRQ/timing measurement.
"""
import importlib.util
import json
import sys
from pathlib import Path
from state_adapter import construct, SECONDARY_KEYS, OTHER_KEYS

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('sony_state_vm', HERE.parent/'shared/pic18_vm.py')
vm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = vm
spec.loader.exec_module(vm)
S = 0x680
PERIPHERALS = (0xFF0, 0xFF2, 0xFD0, 0xF98, 0xFA4)
TWO = {'MOVFF', 'LFSR', 'CALL', 'RCALL', 'GOTO', 'BRA', 'RETURN', 'RETLW'}
SKIP = {'BTFSC', 'BTFSS', 'CPFSGT', 'CPFSLT', 'CPFSEQ', 'DECFSZ', 'DCFSNZ', 'INCFSZ', 'INFSNZ'}


def instruction_cycles(c, trace):
    total = 0
    for i, p in enumerate(trace):
        r = c.decode(p)
        nxt = trace[i+1] if i+1 < len(trace) else None
        n = 2 if r.mnemonic in TWO or r.mnemonic.startswith('TBL') else 1
        if r.mnemonic in vm.BRANCHES and nxt == r.target:
            n = 2
        if r.mnemonic in SKIP and nxt != p+r.length:
            n = 1+c.decode(p+r.length).length//2
        total += n
    return total


def device_hooks(c):
    # Explicit passive interrupt-register model, with independent live bytes.
    for address in PERIPHERALS:
        c.read_hooks[address] = lambda cpu, addr=address: cpu.m[addr]
        c.write_hooks[address] = lambda cpu, value, addr=address: cpu.m.__setitem__(addr, value)


def initialize(c, mode=0, selector=7, fec=(0, 0, 0)):
    values = {0x193: mode, 0xC1: selector, 0xD0: 3,
              0xD2: 0x93, 0xD3: 1, 0xDB: 7, 0xF3: 0,
              0x106: 0xFE, 0x107: 0x7F, S+0x70: mode,
              0x56: 1, 0xE9: 100, 0xEB: 4, 0xFF2: 0xC0, 0xFD0: 0x80}
    for address, value in values.items():
        c.m[address] = value
    c.m[0x197:0x19A] = bytes(x & 255 for x in fec)
    device_hooks(c)
    return c


def main():
    original = (HERE.parent/'shared/stock/S/original.base4000.partial.bin').read_bytes()
    component = construct(original, base=0xD800, state_base=S, radio_quiet=0xC000, nvm_quiet=0xC004)
    image = bytearray(original)
    for section in component['sections']:
        i = section['address'] - 0x4000
        image[i:i+len(section['data'])] = section['data']

    def cpu(mode=0, selector=7, fec=(0, 0, 0)):
        c = initialize(vm.CPU(image), mode, selector, fec)
        c.step_hooks[0xC000] = lambda cpu: setattr(cpu, 'w', 1)
        c.step_hooks[0xC004] = lambda cpu: setattr(cpu, 'w', 1)
        return c

    cases = {'raw_inputs': 0, 'invalid_snapshot': 0, 'readiness': 0,
             'projection': 0, 'invalid_projection': 0,
             'projection_gate_refusal': 0, 'fresh_gate_refusal': 0,
             'irq_restore_matrix': 0, 'critical_path_sweep': 0,
             'scheduled_mode_races': 0}
    for pattern in range(2048):
        c = cpu()
        keys = (0x115, 0x119, 0x11D, 0x121, 0x125, 0x129,
                0x12D, 0x131, 0x135, 0x139, 0x13D)
        for i, key in enumerate(keys):
            c.m[key] = ((pattern >> i) & 1) | 0x80
        c.m[S:S+0x70] = b'\xAB' * 0x70
        c.run(component['exports']['read_inputs'])
        assert c.w == 1 and c.m[S+0x77] == (0x83 if pattern else 0x87)
        assert c.m[S+0x7A] == sum((c.m[k] & 1) << b for k, b in SECONDARY_KEYS)
        assert c.m[S+0x7B] == int(any(c.m[k] & 1 for k in OTHER_KEYS))
        assert c.m[S:S+0x70] == b'\xAB' * 0x70
        assert c.m[S+0x78:S+0x7A] == b'\xFE\x7F'
        cases['raw_inputs'] += 1
    for mode, selector, fec in ((2, 7, (0, 0, 0)), (0, 0, (0, 0, 0)),
                                (0, 4, (0, 0, 0)), (0, 255, (0, 0, 0)),
                                (0, 7, (-21, 0, 0)), (0, 7, (0, 21, 0)),
                                (0, 7, (0, 0, 127))):
        c = cpu(mode, selector, fec)
        c.run(component['exports']['read_inputs'])
        assert c.w == 0 and c.m[S+0x77] == 0
        cases['invalid_snapshot'] += 1
    for d0, d1 in ((0, 0), (2, 0), (3, 0), (255, 0), (0, 1), (0, 0x80)):
        for dd, dc, radio, nvm in ((0, 0, 1, 1), (1, 0, 1, 0), (0, 1, 0, 1), (0, 0, 0, 0)):
            c = cpu(fec=(-20, 20, 0))
            c.m[0xD0], c.m[0xD1], c.m[0xDD], c.m[0xDC] = d0, d1, dd, dc
            c.step_hooks[0xC000] = lambda cpu, val=radio: setattr(cpu, 'w', val)
            c.step_hooks[0xC004] = lambda cpu, val=nvm: setattr(cpu, 'w', val)
            c.run(component['exports']['read_inputs'])
            edit = dd == 0 and dc == 0 and not d1 & 0x80 and (d1 != 0 or d0 >= 3)
            assert c.m[S+0x77] == 0x80 | int(edit) | radio*2 | (nvm*4 if edit else 0)
            cases['readiness'] += 1
    for mode in (0, 1):
        for selector in (1, 2, 3, 7):
            for requested in range(16):
                for head, model in ((0, 0), (7, 0), (0x3F, 0x3F), (0x25, 0x1A)):
                    c = cpu(1-mode, 7, (1, 2, 3))
                    c.m[0xDB], c.m[0xF3] = 0xA9, 0xB8
                    c.m[S+1], c.m[S+4], c.m[S+5], c.m[S+6] = mode, selector, head, model
                    c.m[S+0x14:S+0x17] = bytes((236, 0, 20))
                    before = bytes(c.m[S:S+0xB0])
                    c.w = requested
                    c.run(component['exports']['apply_native_state'])
                    assert c.w == 1
                    assert c.m[0x193] == (mode if requested & 1 else 1-mode)
                    assert c.m[0xC1] == (selector if requested & 4 else 7)
                    assert bytes(c.m[0x197:0x19A]) == (bytes((236, 0, 20)) if requested & 2 else bytes((1, 2, 3)))
                    assert c.m[0xDB] == (0xA8 | (head & 7) if requested & 8 else 0xA9)
                    assert c.m[0xF3] == (0xB8 | (model & 7) if requested & 8 else 0xB8)
                    assert c.m[S:S+0xB0] == before
                    # Any native queue or live camera protocol state mutation is a failure.
                    touched = {entry[0] for entry in c.writes}
                    assert not touched.intersection(range(0xE6, 0xEC))
                    assert not touched.intersection(range(0x400, 0x464))
                    assert not touched.intersection(range(0x194, 0x197))
                    cases['projection'] += 1
    for requested, offset, value in ((16, 1, 0), (1, 1, 2), (2, 0x14, 21), (4, 4, 0), (4, 4, 4)):
        c = cpu()
        c.m[S+1], c.m[S+4] = 0, 7
        c.m[S+offset] = value
        before = bytes(c.m[:0x464])
        c.w = requested
        c.run(component['exports']['apply_native_state'])
        assert c.w == 0 and c.m[:0x464] == before
        cases['invalid_projection'] += 1

    # The race/critical-section tests use the real reviewed quiet predicate,
    # not the ABI-only readiness stubs above.
    sys.path.insert(0, str(HERE/'radio'))
    from fast_empty_queue import construct as construct_queue
    queue, queue_meta = construct_queue(0xB200, S+0x30, S+0x117)
    quiet = queue_meta['labels']['sony_air2_quiet']
    actual = construct(original, base=0xD800, state_base=S, radio_quiet=quiet, nvm_quiet=quiet)
    actual_image = bytearray(original)
    actual_image[0xB200-0x4000:0xB200-0x4000+len(queue)] = queue
    for section in actual['sections']:
        i = section['address']-0x4000
        actual_image[i:i+len(section['data'])] = section['data']
    labels = actual['exports']

    def ready(c=None, mode=0):
        c = initialize(c or vm.CPU(actual_image), mode, 7, (1, 2, 3))
        c.m[S+1], c.m[S+4], c.m[S+5], c.m[S+6] = 1-mode, 2, 0x25, 0x1A
        c.m[S+0x14:S+0x17] = bytes((236, 0, 20))
        c.w = 15
        c.track_trace = True
        return c

    faults = ((0xDD, 1), (0xDC, 1), (0xD0, 2), (0xD1, 128),
              (0x193, 1), (0xD8, 1), (0xE8, 1), (0x56, 2),
              (0x48, 1), (0x194, 2), (0x58, 2), (0xFF0, 1),
              (0xFF0, 2), (0xF98, 16), (0xFA4, 128), (0xE9, 99))
    for address, value in faults:
        c = ready()
        c.m[address] = value
        before = bytes(c.m[:0x464])
        irq = c.m[0xFF2]
        c.run(labels['apply_native_state'])
        assert c.w == 0 and bytes(c.m[:0x464]) == before
        assert c.m[0xFF2] == irq
        assert not any(a == 0xFF2 for a, _ in c.writes)
        cases['projection_gate_refusal'] += 1

    for address, value in faults:
        c = ready()
        changed = []
        def race_at_saved_irq(cpu, addr=address, val=value):
            if not changed:
                cpu.m[addr] = val
                changed.append(bytes(cpu.m[:0x464]))
            return cpu.m[0xFF2]
        c.read_hooks[0xFF2] = race_at_saved_irq
        c.run(labels['apply_native_state'])
        assert changed and c.w == 0 and bytes(c.m[:0x464]) == changed[0]
        assert c.m[0xFF2] == 0xC0 and c.m[0xFD0] == 0x80
        cases['fresh_gate_refusal'] += 1

    critical = []
    for mode in (0, 1):
        for requested in range(16):
            for gie in (0, 0x40, 0x80, 0xC0):
                for ipen in (0, 0x80):
                    c = ready(mode=mode)
                    c.m[0xFF2], c.m[0xFD0] = gie | 0x12, ipen
                    c.w = requested
                    # Model a new unrelated live IF/enable-low-bit change
                    # after masking. Whole-byte restoration would erase it.
                    saved = []
                    def preserve_pending(cpu, value):
                        cpu.m[0xFF2] = value
                        if cpu.pc == labels['apply_mask_begin']+2:
                            cpu.m[0xFF2] |= 0x25
                            saved.append(1)
                    c.write_hooks[0xFF2] = preserve_pending
                    c.run(labels['apply_native_state'])
                    assert c.w == 1 and saved
                    assert c.m[0xFF2] == gie | 0x37 and c.m[0xFD0] == ipen
                    assert not any(a == 0xFD0 for a, _ in c.writes)
                    begin = c.trace.index(labels['apply_mask_begin'])
                    end = c.trace.index(labels['apply_mask_end'])
                    critical.append({'mode': mode, 'mask': requested,
                                     'gie': gie, 'ipen': ipen,
                                     'instructions': end-begin,
                                     'instruction_cycles': instruction_cycles(c, c.trace[begin:end])})
                    cases['irq_restore_matrix'] += 1

    # Sweep every valid selector for both the explicitly selected and current
    # selector paths. Include extreme legal FEC and model/head combinations.
    for mode in (0, 1):
        for native_selector in (1, 2, 3, 7):
            for selector in (1, 2, 3, 7):
                for requested in range(16):
                    for head, model in ((0, 0), (7, 0), (0x3F, 0x3F), (0x25, 0x1A)):
                        c = ready(mode=mode)
                        c.m[0xC1] = native_selector
                        c.m[S+4], c.m[S+5], c.m[S+6] = selector, head, model
                        c.w = requested
                        c.run(labels['apply_native_state'])
                        assert c.w == 1 and c.m[0xFF2] == 0xC0
                        begin = c.trace.index(labels['apply_mask_begin'])
                        end = c.trace.index(labels['apply_mask_end'])
                        critical.append({'mode': mode, 'native_selector': native_selector,
                                         'selector': selector, 'head': head, 'model': model,
                                         'mask': requested, 'gie': 0xC0, 'ipen': 0x80,
                                         'instructions': end-begin,
                                         'instruction_cycles': instruction_cycles(c, c.trace[begin:end])})
                        cases['critical_path_sweep'] += 1

    class ScheduledModeCPU(vm.CPU):
        def __init__(self, boundary=None, priority='high'):
            super().__init__(actual_image)
            self.boundary, self.priority = boundary, priority
            self.arrived = self.delivered = self.observing = False
            self.delivery_writes = None

        def observe(self):
            if self.boundary is not None and not self.arrived and self.steps >= self.boundary:
                self.arrived = True
                self.m[0xFF0] |= 1
                self.m[0xFF2] |= 0x25
            enabled = self.m[0xFF2] & (0x80 if self.priority == 'high' else 0x40)
            if self.arrived and not self.delivered and enabled:
                self.delivered = True
                # Bounded camera-state-writer model, not a full ISR. Native
                # mode becomes MAN; its event acknowledgement is independent.
                self.m[0x193] = 1
                self.m[0xFF0] &= ~1
                self.delivery_writes = len(self.writes)

        def decode(self, pc):
            if not self.observing and pc == self.pc:
                self.observing = True
                self.observe()
                self.observing = False
            return super().decode(pc)

    race_boundaries = {}
    for requested in (1, 15):
        for gie, priority in ((0x80, 'high'), (0xC0, 'high'), (0x40, 'low'), (0xC0, 'low')):
            ref = ready(ScheduledModeCPU())
            ref.m[0xFF2] = gie
            ref.m[S+1] = 0  # A stale core TTL target must never overwrite MAN.
            ref.w = requested
            ref.run(labels['apply_native_state'])
            race_boundaries['%d/%02X/%s' % (requested, gie, priority)] = len(ref.trace)+1
            for boundary in range(len(ref.trace)+1):
                c = ready(ScheduledModeCPU(boundary, priority))
                c.m[0xFF2] = gie
                c.m[S+1] = 0
                c.w = requested
                c.run(labels['apply_native_state'])
                accepted_result = c.w
                c.observe()
                assert c.arrived and c.delivered
                assert c.m[0x193] == 1, (requested, gie, priority, boundary, accepted_result)
                assert not any(a == 0x193 for a, _ in c.writes[c.delivery_writes:])
                assert c.m[0xFF2] == gie | 0x25 and c.m[0xFD0] == 0x80
                cases['scheduled_mode_races'] += 1
    report = {'result': 'PASS', 'cases': cases, 'total': sum(cases.values()),
              'native_helpers': ['AB0C', '5CD8', '7B3A', '8816'],
              'explicit_stubs': ['radio_quiet', 'nvm_quiet'],
              'atomic_tests_use': 'actual Sony quiet predicate plus bounded scheduled camera-state-writer',
              'critical_section_max': max(critical, key=lambda row: row['instruction_cycles']),
              'critical_section_min_cycles': min(row['instruction_cycles'] for row in critical),
              'race_boundaries': race_boundaries,
              'code_bytes': len(actual['sections'][0]['data']),
              'does_not_establish': ['physical camera quiet', 'full ISR priority model', 'RF timing', 'flash persistence']}
    if '--no-report' not in sys.argv:
        (HERE/'state_adapter_tests.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    print('PASS %d Sony state adapter cases; native helpers executed' % sum(cases.values()))


if __name__ == '__main__':
    main()
