#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Sony normal foreground hook set; every replaced instruction is validated."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location('sony_hook_' + name, HERE/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def construct(original, *, code_base, profile, imports=None, app_base=0x4000):
    if app_base != 0x4000 or profile.get('model_tag') != 'S':
        raise ValueError('Sony A6 profile required')
    s = int(profile['state_base'])
    imports = dict(imports or {})
    required = ('init', 'service', 'power_edit', 'select_row', 'secondary_press',
                'idle_expired', 'redraw', 'redraw_icons')
    if profile.get('page_hint_on_chord'):
        required += ('page_hint',)
    if any(not imports.get(k) for k in required):
        raise ValueError('all resolved core/backend imports required')
    sections, hooks, exports, parts = [], [], {}, {}
    cursor = code_base

    def add(name, component):
        nonlocal cursor
        sections.extend(component['sections'])
        hooks.extend(component.get('hooks', []))
        exports.update(component['exports'])
        parts[name] = component.get('metadata', {})
        cursor = max(r['address'] + len(r['data']) for r in component['sections'])

    life = load('life', 'lifecycle_adapter.py').construct(
        original, base=cursor, state_base=s,
        core_init=imports['init'], core_service=imports['service'])
    add('lifecycle', life)
    context = {k: exports[k] for k in ('context_enter', 'context_leave')}
    add('controls', load('controls', 'control_adapter.py').construct(
        original, base=cursor, state_base=s, **context,
        power_edit=imports['power_edit'], redraw=imports['redraw'],
        idle_expired=imports['idle_expired']))
    add('keys', load('keys', 'display/keys/native_key_adapter.py').construct(
        original, base=cursor, state_base=s, **context,
        secondary_press=imports['secondary_press'], select_row=imports['select_row']))
    # Final LCD-boundary normalization is a separate reviewed component: native
    # selector/model helpers later in the call chain can overwrite DEF icons.
    display_path = HERE/'display/final_display_hook.py'
    if not display_path.exists():
        raise ValueError('final Sony LCD commit hook not yet available')
    add('lcd_commit', load('lcd_commit', 'display/final_display_hook.py').construct(
        original, base=cursor, state_base=s, **context,
        redraw_icons=imports['redraw_icons']))
    if cursor > 0xF800:
        raise ValueError('Sony hook code exceeds owned tail')
    return {'sections': sections, 'hooks': hooks, 'exports': exports,
            'unresolved_imports': [], 'metadata': {'parts': parts,
                'context_addresses': list(life['metadata']['saved_native_registers']),
                'page_hint_lifecycle': {
                    'page_hint_on_chord': bool(profile.get('page_hint_on_chord')),
                    'release_redraw': bool(profile.get('release_redraw')),
                    'entry': imports.get('page_hint'),
                    'owner': 'shared successful page commit / stable full-release callbacks',
                    'native_redraw_may_end_hint_earlier': True,
                },
                'original_hss_modified': False, 'device_boot_verified': False}}
