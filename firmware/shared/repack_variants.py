#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Strict offline repacker for stock-HSS N/S/F/O AIR2 native ports.

The updater is treated only as a container. This program never starts an EXE,
opens USB, flashes hardware, or claims that an offline check proves bootability.
All original bytes except reviewed application hooks and empty-ROM additions
must survive. Header, opaque bytes, configuration records and loader survive.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inspect_variants as stock

BASE, KNOWN_END, NVM_START = 0x4000, 0x10000, 0xF800
REQUIRED_CHECKS = (
    'native_hook_preimages', 'instruction_boundaries', 'private_ram_allocation',
    'native_calling_conventions', 'radio_queue_backpressure',
    'original_hss_paths_preserved', 'persistence_backend',
    'core_policy_tests', 'native_adapter_tests',
)


class BuildError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise BuildError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def integer(value, field):
    require(type(value) is int, field + ' must be an integer')
    return value


def hex_bytes(value, field):
    require(isinstance(value, str), field + ' must be a hexadecimal string')
    try:
        result = bytes.fromhex(value)
    except ValueError as exc:
        raise BuildError(field + ': invalid hexadecimal') from exc
    require(bool(result), field + ' must not be empty')
    return result


def instruction_size(word):
    """PIC18 double-word opcodes; continuation words must not be split."""
    if (word & 0xF000) == 0xC000:  # MOVFF
        return 4
    if (word & 0xFE00) == 0xEC00:  # CALL, with optional fast bit
        return 4
    if (word & 0xFF00) == 0xEF00:  # GOTO
        return 4
    if (word & 0xFFC0) == 0xEE00:  # LFSR
        return 4
    return 2


def check_instruction_sequence(data, description):
    require(len(data) % 2 == 0, description + ': odd instruction length')
    position = 0
    while position < len(data):
        word = int.from_bytes(data[position:position + 2], 'little')
        require((word & 0xF000) != 0xF000,
                description + ': starts on a continuation word')
        size = instruction_size(word)
        require(position + size <= len(data), description + ': split instruction')
        if size == 4:
            following = int.from_bytes(data[position + 2:position + 4], 'little')
            require((following & 0xF000) == 0xF000,
                    description + ': invalid continuation word')
        position += size


def ranges_overlap(start, end, other_start, other_end):
    return start < other_end and other_start < end


class Variant:
    def __init__(self, model, source=None):
        require(model in stock.MODELS, 'Unsupported target')
        self.model = model
        self.folder = HERE / 'stock' / model
        self.profile = json.loads((self.folder / 'profile.json').read_text('utf-8'))
        profile = self.profile
        require(profile['source_sha256'] == stock.MODELS[model][1], 'Unpinned profile')
        local_source = HERE.parent / 'inputs' / profile['source']
        # Standalone source archives use the documented inputs/ layout. An
        # explicit source always wins; a present but wrong local file must fail
        # fingerprint validation below rather than silently use another input.
        self.source = (Path(source) if source is not None else
                       local_source if local_source.is_file() else
                       stock.WORK / profile['source'])
        self.outer = self.source.read_bytes()
        require(sha(self.outer) == profile['source_sha256'], 'Source EXE fingerprint mismatch')
        require(len(self.outer) == profile['source_size'], 'Source EXE size mismatch')
        self.start, self.end = profile['hex_start'], profile['hex_end']
        require(self.start == stock.MODELS[model][2], 'Unpinned HEX resource offset')
        self.container_module = stock.load('multi_strict_hex', stock.HELPERS / 'container.py')
        self.hex = self.container_module.HexImage(self.outer[self.start:self.end])
        require(sha(self.hex.text) == profile['hex_sha256'], 'Original HEX fingerprint mismatch')
        require(self.hex.layout_sha256() == profile['hex_layout_sha256'], 'HEX layout mismatch')
        require([list(row) for row in self.hex.spans()] == profile['hex_spans'], 'HEX sparse spans mismatch')
        require(sha(self.outer[:self.start] + self.outer[self.end:]) == profile['outside_hex_sha256'],
                'Original updater/loader fingerprint mismatch')
        self.plain = (self.folder / 'original.base4000.partial.bin').read_bytes()
        self.mask = (self.folder / 'original.known_mask.bin').read_bytes()
        require(sha(self.plain) == profile['partial_plaintext_sha256'], 'Partial image fingerprint mismatch')
        require(sha(self.mask) == profile['known_mask_sha256'], 'Known-mask fingerprint mismatch')
        self.codec = stock.load('multi_strict_codec', stock.HELPERS / 'reference_codec.py').ReferenceCodec()
        wire = bytes(self.hex.memory[a] for a in range(BASE + 2, KNOWN_END))
        require(self.codec.decode(BASE + 2, wire) == self.plain[2:KNOWN_END - BASE],
                'Stock decoding mismatch')

    def build(self, plan, require_complete=True):
        """Return bytes/report, without writing anything or executing the result.

        require_complete=False is solely for in-memory repacker unit tests.
        The command-line writer always requires all reviewed checks to pass.
        """
        require(plan.get('schema_version') == 1, 'Unsupported patch-plan schema')
        require(plan.get('model') == self.model, 'Patch plan targets another model')
        require(plan.get('stock_sha256') == self.profile['source_sha256'], 'Patch plan stock mismatch')
        if require_complete:
            validation = plan.get('validation', {})
            for check in REQUIRED_CHECKS:
                require(validation.get(check) is True, 'Required verification not passed: ' + check)
            require(re.fullmatch(r'[0-9a-f]{64}', plan.get('verification_report_sha256', '')) is not None,
                    'Missing bound verification report')
        hooks, sections = plan.get('hooks', []), plan.get('sections', [])
        require(isinstance(hooks, list) and isinstance(sections, list), 'Invalid patch entries')
        require(bool(hooks) and bool(sections), 'AIR2 requires both native hooks and added code')
        protected = [(BASE, 0x4100, 'original header'),
                     (NVM_START, stock.END, 'NVM and opaque high tail')]
        for row in plan.get('protected_ranges', []):
            start, end = integer(row['start'], 'protected start'), integer(row['end'], 'protected end')
            require(BASE <= start < end <= stock.END, 'Invalid protected range')
            protected.append((start, end, str(row.get('label', 'native protected code'))))
        if require_complete:
            require(any(s <= 0x4108 and e > 0x4108 for s, e, _ in protected),
                    'Interrupt entry must be protected')
            require(len(plan.get('protected_ranges', [])) >= 3, 'Missing model HSS/camera/RF protections')
        result = bytearray(self.plain)
        patches, covered = [], set()
        tail = self.profile['last_non_ff_end_exclusive_below_10000']
        for kind, entries in [('hook', hooks), ('section', sections)]:
            for row in entries:
                address = integer(row['address'], kind + ' address')
                data = hex_bytes(row['replacement_hex'] if kind == 'hook' else row['data_hex'], kind)
                end = address + len(data)
                require(address % 2 == 0 and len(data) % 2 == 0, 'Unaligned code edit')
                require(0x4100 <= address < end <= NVM_START, 'Edit outside permitted application area')
                for pstart, pend, label in protected:
                    require(not ranges_overlap(address, end, pstart, pend), 'Edit intersects ' + label)
                positions = set(range(address, end))
                require(not covered.intersection(positions), 'Overlapping patch entries')
                covered.update(positions)
                old = self.plain[address - BASE:end - BASE]
                require(all(self.mask[address - BASE:end - BASE]), 'Edit touches unknown plaintext')
                if kind == 'hook':
                    expected = hex_bytes(row['expected_hex'], 'hook preimage')
                    require(len(expected) == len(data), 'Hook length changed')
                    require(old == expected, 'Hook preimage mismatch at %04X' % address)
                    require(end <= tail, 'Hook outside original application code')
                    check_instruction_sequence(expected, 'Hook original %04X' % address)
                    check_instruction_sequence(data, 'Hook replacement %04X' % address)
                    if address > 0x4100:
                        previous = int.from_bytes(self.plain[address - BASE - 2:address - BASE], 'little')
                        require(instruction_size(previous) != 4, 'Hook starts inside a double-word instruction')
                else:
                    require(address >= ((tail + 1) & ~1), 'Section overlaps original application')
                    require(old == b'\xff' * len(old), 'Section occupies nonempty stock ROM')
                result[address - BASE:end - BASE] = data
                patches.append({'kind': kind, 'address': address, 'length': len(data),
                                'role': row.get('role', ''), 'before_sha256': sha(old), 'after_sha256': sha(data)})
        require(result[:0x100] == self.plain[:0x100], 'Original header changed')
        require(result[NVM_START - BASE:] == self.plain[NVM_START - BASE:], 'Original reserved region changed')
        changed = {BASE + index for index, (before, after) in enumerate(zip(self.plain, result)) if before != after}
        require(changed and changed.issubset(covered), 'Undeclared changes')
        replacement = {}
        # The codec is address-indexed. Encode declared ranges, retaining every
        # byte of the original opaque transport stream outside those ranges.
        for row in patches:
            start, length = row['address'], row['length']
            encoded = self.codec.encode(start, bytes(result[start - BASE:start - BASE + length]))
            replacement.update({start + i: value for i, value in enumerate(encoded)})
        new_hex = self.hex.replace_opaque_bytes(replacement)
        rebuilt = self.outer[:self.start] + new_hex.text + self.outer[self.end:]
        require(len(rebuilt) == len(self.outer), 'EXE size changed')
        require(rebuilt[:self.start] == self.outer[:self.start] and rebuilt[self.end:] == self.outer[self.end:],
                'GUI/loader/container changed')
        decoded = self.codec.decode(BASE + 2, bytes(new_hex.memory[a] for a in range(BASE + 2, KNOWN_END)))
        require(decoded == bytes(result[2:KNOWN_END - BASE]), 'Full codec readback mismatch')
        for address, value in self.hex.memory.items():
            if address not in covered:
                require(new_hex.memory[address] == value, 'Undeclared opaque transport edit')
        for start, end, label in protected:
            require(all(new_hex.memory[a] == self.hex.memory[a] for a in range(start, end) if a in self.hex.memory),
                    'Protected transport bytes changed: ' + label)
        report = {
            'model': self.model, 'stock_sha256': self.profile['source_sha256'],
            'output_sha256': sha(rebuilt), 'output_hex_sha256': sha(new_hex.text),
            'output_partial_plaintext_sha256': sha(result), 'plan_sha256': sha(json.dumps(plan, sort_keys=True).encode('utf-8')),
            'patched_ranges': patches, 'changed_plaintext_byte_count': len(changed),
            'outside_hex_byte_identical': True, 'header_byte_identical': True,
            'sparse_hex_layout_identical': True, 'opaque_unknown_bytes_identical': True,
            'protected_ranges_byte_identical': True, 'full_codec_readback_exact': True,
            'protected_ranges': [{'start': start, 'end': end, 'label': label}
                                 for start, end, label in protected],
            'updater_executed': False, 'device_accessed': False, 'device_boot_verified': False,
            'validation': plan.get('validation', {}), 'complete_offline_gate_required': require_complete,
        }
        return rebuilt, new_hex.text, bytes(result), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=tuple(stock.MODELS), required=True)
    parser.add_argument('--source', type=Path, help='Pinned original updater, never executed')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--verification', type=Path, required=True,
                        help='Independent component/integration verification report bound by the plan')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text('utf-8'))
    verification_bytes = args.verification.read_bytes()
    require(sha(verification_bytes) == plan.get('verification_report_sha256'),
            'Verification report fingerprint mismatch')
    verification = json.loads(verification_bytes.decode('utf-8'))
    require(verification.get('model') == args.model and
            verification.get('stock_sha256') == stock.MODELS[args.model][1],
            'Verification report targets different stock/model')
    for check in REQUIRED_CHECKS:
        require(verification.get('validation', {}).get(check) is True,
                'Verification report lacks passed check: ' + check)
    variant = Variant(args.model, args.source)
    exe, hex_text, plain, report = variant.build(plan)
    report['plan_file_sha256'] = sha(args.plan.read_bytes())
    report['verification_report_sha256'] = sha(verification_bytes)
    output = args.output.resolve()
    name = 'Air-Remote-TTL-%s-AIR2-P8-M1' % args.model
    stock.write_same_or_new(output / (name + '.exe'), exe)
    stock.write_same_or_new(output / (name + '.hex'), hex_text)
    stock.write_same_or_new(output / (name + '.partial.bin'), plain)
    stock.write_same_or_new(output / 'verification.json', (json.dumps(report, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'model': args.model, 'output': str(output), 'sha256': report['output_sha256'],
                      'device_boot_verified': False}, indent=2))


if __name__ == '__main__':
    main()
