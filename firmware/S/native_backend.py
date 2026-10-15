#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Sony A6 native ABI adapter for the shared AIR2-P8 runtime.

No installer or peripheral access occurs here. Persistence is linked separately
by shared/build_variants.py; the native HSS and RF scheduler remain stock.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    sys.path.insert(0, str((HERE/path).parent))
    spec = importlib.util.spec_from_file_location('sony_' + name, HERE/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def construct(original, *, app_base=0x4000, code_base, profile, imports=None):
    if app_base != 0x4000 or profile.get('model_tag') != 'S':
        raise ValueError('Sony A6 profile required')
    stock = (HERE.parent/'shared/stock/S/original.base4000.partial.bin').read_bytes()
    if hashlib.sha256(original).digest() != hashlib.sha256(stock).digest():
        raise ValueError('Sony A6 baseline mismatch')
    s = int(profile['state_base'])
    if s != 0x680 or profile.get('state_span') != 0x180:
        raise ValueError('reviewed Sony private state allocation required')
    imports = dict(imports or {})
    if not imports.get('display_row'):
        raise ValueError('resolved shared display_row import required')
    for key in ('native_input_gate_proven', 'native_radio_gate_proven'):
        if profile.get(key) is not True:
            raise ValueError('missing native gate evidence: ' + key)
    sections, exports, parts = [], {}, {}
    cursor = code_base

    def add(name, component):
        nonlocal cursor
        sections.extend(component['sections'])
        parts[name] = component.get('metadata', {})
        cursor = max(r['address'] + len(r['data']) for r in component['sections'])
        return component['exports']

    radio = load('radio', 'radio/fast_empty_queue.py')
    code, info = radio.construct(cursor, frame_ram=s+0x30, irq_ram=s+0x117)
    sections.append({'address': cursor, 'data': code, 'role': 'sony_atomic_empty_queue'})
    parts['radio'] = info
    cursor += len(code)
    exports['tx_frame'] = info['labels']['sony_air2_fast_try_queue']
    exports['quiet'] = info['labels']['sony_air2_quiet']
    state = load('state', 'state_adapter.py').construct(
        original, base=cursor, state_base=s, radio_quiet=exports['quiet'],
        nvm_quiet=exports['quiet'] if profile.get('native_nv_gate_proven') is True else None)
    state_exports = add('state', state)
    exports.update({k: state_exports[k] for k in ('read_inputs', 'apply_native_state')})
    rows = load('rows', 'display/canonical_renderer.py').construct(
        original, cursor, state_base=s, display_row=imports['display_row'])
    row_exports = add('rows', rows)
    full = load('full', 'display/canonical_full_renderer.py').construct(
        original, cursor, state_base=s, redraw_rows=row_exports['redraw_rows'])
    full_exports = add('full', full)
    exports.update({k: full_exports[k] for k in ('redraw', 'redraw_icons', 'page_hint')})
    if cursor > 0xF800:
        raise ValueError('Sony backend exceeds owned code tail')
    return {'sections': sections, 'hooks': [], 'exports': exports,
            'unresolved_imports': [], 'metadata': {'model': 'S', 'parts': parts,
                'nv_linkage': 'shared persistence_backend with real read_inputs',
                'original_hss_modified': False, 'device_boot_verified': False}}
