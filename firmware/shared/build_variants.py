#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Link one non-Canon AIR2 target, replay it, then repack its stock updater.

Run one model per Python process: native adapters have model-local import names.
No updater execution, USB I/O, installation or flashing takes place here.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import inspect
import json
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(HERE))
import inspect_variants as stock
from repack_variants import Variant, REQUIRED_CHECKS, BuildError, require


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def call_construct(module, original, **kwargs):
    signature = inspect.signature(module.construct)
    supplied = {name: value for name, value in kwargs.items() if name in signature.parameters}
    return module.construct(original, **supplied)


def component_end(component):
    require(bool(component.get('sections')), 'Component has no code')
    return max(section['address'] + len(section['data']) for section in component['sections'])


def component_shape(component):
    return [(row['address'], len(row['data']), row['role']) for row in component['sections']]


def jsonable(value):
    if isinstance(value, bytes):
        return {'hex': value.hex()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value


def json_bytes(value):
    return (json.dumps(jsonable(value), ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def link(model, profile, source=None):
    """Deterministic in-memory two-pass linking; does not imply qualification."""
    variant = Variant(model, source)
    original = variant.plain
    require(profile.get('model_tag') == model, 'Profile model mismatch')
    require(profile.get('state_base') == 0x680 and profile.get('state_span') == 0x180,
            'Profile does not use reviewed common private RAM allocation')
    require(profile.get('code_limit') == 0xF800, 'Unreviewed code/NVM boundary')
    require(profile.get('nv_enabled') is True, 'The full P8 port requires persistence')
    sys.path.insert(0, str(PROJECT / model))
    backend_module = load_module('native_backend', PROJECT / model / 'native_backend.py')
    hook_module = load_module('native_hooks', PROJECT / model / 'native_hooks.py')
    core_module = load_module('runtime_generator', HERE / 'runtime_generator.py')
    nv_module = load_module('persistence_backend', HERE / 'persistence_backend.py')
    code_base = (variant.profile['last_non_ff_end_exclusive_below_10000'] + 1) & ~1
    common = {'app_base': 0x4000, 'profile': profile, 'state_base': profile['state_base']}
    # These placeholders only determine fixed-width CALL layout. No first-pass
    # image is executed or written. The second pass resolves every import.
    placeholders = {name: 0x4100 for name in core_module.required_imports(profile)}
    core_first = call_construct(core_module, original, code_base=code_base,
                                backend={'exports': placeholders}, **common)
    backend_first = call_construct(backend_module, original, code_base=component_end(core_first),
                                   imports=core_first['exports'], core_imports=core_first['exports'], **common)
    nv_first = call_construct(nv_module, original, code_origin=component_end(backend_first),
                              code_base=component_end(backend_first),
                              imports={'read_inputs': backend_first['exports']['read_inputs']},
                              backend={'persistence': profile.get('persistence', {})}, **common)
    require(nv_first.get('metadata', {}).get('nv_enabled') is True, 'Persistence proof gate is disabled')
    native_imports = dict(backend_first['exports'])
    native_imports.update(nv_first['exports'])
    core = call_construct(core_module, original, code_base=code_base,
                          backend={'exports': native_imports}, **common)
    backend = call_construct(backend_module, original, code_base=component_end(core),
                             imports=core['exports'], core_imports=core['exports'], **common)
    nv = call_construct(nv_module, original, code_origin=component_end(backend),
                        code_base=component_end(backend),
                        imports={'read_inputs': backend['exports']['read_inputs']},
                        backend={'persistence': profile.get('persistence', {})}, **common)
    for first, final in ((core_first, core), (backend_first, backend), (nv_first, nv)):
        require(component_shape(first) == component_shape(final), 'Unstable two-pass code layout')
        require(first['exports'] == final['exports'], 'Unstable two-pass export addresses')
    combined_imports = dict(backend['exports'])
    combined_imports.update(core['exports'])
    hooks = call_construct(hook_module, original, code_base=component_end(nv),
                           imports=combined_imports, backend_exports=backend['exports'],
                           core=core, backend=backend, core_imports=core['exports'], **common)
    components = {'core': core, 'backend': backend, 'persistence': nv, 'hooks': hooks}
    image = bytearray(original)
    covered = set()
    plan = {'schema_version': 1, 'model': model, 'stock_sha256': variant.profile['source_sha256'],
            'hooks': [], 'sections': [], 'protected_ranges': [], 'validation': {},
            'profile_sha256': sha(json_bytes(profile))}
    for name, component in components.items():
        require(not component.get('unresolved_imports'), name + ' has unresolved imports: ' +
                str(component.get('unresolved_imports')))
        for export_name, address in component['exports'].items():
            require(isinstance(address, int) and address % 2 == 0 and code_base <= address < 0xF800,
                    'Export is not in added application code: ' + name + '.' + export_name)
        for section in component['sections']:
            start, data = section['address'], section['data']
            require(isinstance(data, bytes), 'Section must contain immutable assembled bytes')
            end = start + len(data)
            require(start >= code_base and end <= 0xF800, 'Code exceeds original empty tail')
            require(not covered.intersection(range(start, end)), 'Linked sections overlap')
            covered.update(range(start, end))
            require(original[start-0x4000:end-0x4000] == b'\xff' * len(data), 'Stock code cave is occupied')
            image[start-0x4000:end-0x4000] = data
            plan['sections'].append({'address': start, 'data_hex': data.hex(), 'role': section['role']})
        for hook in component.get('hooks', []):
            start = hook['address']
            expected = bytes.fromhex(hook['expected_hex'])
            replacement = bytes.fromhex(hook.get('new_hex', hook.get('replacement_hex', '')))
            require(len(expected) == len(replacement) and expected, 'Invalid native hook width')
            require(original[start-0x4000:start-0x4000+len(expected)] == expected, 'Native hook preimage mismatch')
            require(not covered.intersection(range(start, start+len(expected))), 'Hook overlaps another edit')
            covered.update(range(start, start+len(expected)))
            image[start-0x4000:start-0x4000+len(expected)] = replacement
            plan['hooks'].append({'address': start, 'expected_hex': expected.hex(),
                                  'replacement_hex': replacement.hex(), 'role': hook['role'],
                                  'continuation': hook.get('continuation'), 'evidence': hook.get('evidence', '')})
        plan['protected_ranges'].extend(component.get('protected_ranges', []))
    plan['protected_ranges'].extend(profile.get('protected_ranges', []))
    require(plan['hooks'], 'No native UI hooks were linked')
    # Exercise the strict repacker entirely in memory before calling test code.
    _, _, decoded, _ = variant.build(plan, require_complete=False)
    require(decoded == bytes(image), 'Linker/repacker disagree on the resulting program')
    return {'variant': variant, 'profile': profile, 'components': components,
            'image': bytes(image), 'mask': variant.mask, 'plan': plan,
            'code_end': max(component_end(c) for c in components.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, choices=tuple(stock.MODELS))
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text('utf-8'))
    require(profile.get('offline_qualification_complete') is True, 'Model qualification is not complete')
    result = link(args.model, profile, args.source)
    require(profile.get('qualification', {}).get('image_sha256') == sha(result['image']),
            'Linked image differs from the reviewed qualification')
    tester = load_module('test_integrated_firmware', HERE / 'test_integrated_firmware.py')
    # Include nested native generators and the assembler/codec/test tools, not
    # only their public wrappers. These inputs are fixed during final replay.
    source_paths = sorted(set(HERE.glob('*.py')) |
                          set((HERE/'helpers').glob('*.py')) |
                          set((PROJECT/args.model).rglob('*.py')))
    replay = tester.verify_model(args.model, result['image'], result['mask'], profile,
                                 result['components'], hooks=result['plan']['hooks'],
                                 source_paths=source_paths)
    require(replay.get('status') == 'PASS_BOUNDED_LINKED_CASES' and
            replay.get('full_integration_pass') is True and
            not replay.get('coverage_pending'), 'Final linked replay has incomplete coverage')
    require(replay.get('image_sha256') == sha(result['image']), 'Replay image binding mismatch')
    # Qualification booleans are supplied by a reviewed target profile; replay
    # is independent and cannot be skipped merely by setting profile flags.
    validation = dict(profile.get('validation', {}))
    for check_name in REQUIRED_CHECKS:
        require(validation.get(check_name) is True, 'Target profile lacks check: ' + check_name)
    verification = {'model': args.model, 'stock_sha256': result['variant'].profile['source_sha256'],
                    'validation': validation, 'integration': replay,
                    'qualification': profile.get('qualification', {}),
                    'final_partial_plaintext_sha256': sha(result['image']),
                    'nv_enabled': True, 'device_boot_verified': False,
                    'profile_sha256': sha(json_bytes(profile))}
    verification_data = json_bytes(verification)
    plan = result['plan']
    plan['validation'] = validation
    plan['verification_report_sha256'] = sha(verification_data)
    exe, hex_text, partial, report = result['variant'].build(plan)
    require(partial == result['image'], 'Final repacking changed the linked image')
    plan_data = json_bytes(plan)
    report['plan_file_sha256'] = sha(plan_data)
    report['verification_report_sha256'] = sha(verification_data)
    output = args.output.resolve()
    name = 'Air-Remote-TTL-%s-AIR2-P8-M2' % args.model
    for filename, data in (
        (name+'.exe', exe), (name+'.hex', hex_text), (name+'.partial.bin', partial),
        ('profile.json', json_bytes(profile)), ('patch_plan.json', plan_data),
        ('final_image_verification.json', verification_data), ('verification.json', json_bytes(report)),
        ('linked_components.json', json_bytes(result['components'])),
    ):
        stock.write_same_or_new(output/filename, data)
    print(json.dumps({'model': args.model, 'code_end': hex(result['code_end']),
                      'output': str(output), 'sha256': sha(exe), 'device_boot_verified': False}, indent=2))


if __name__ == '__main__':
    main()
