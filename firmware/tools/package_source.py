# -*- coding: utf-8 -*-
#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Archive authored multi-mount port sources, without vendor firmware/private data."""
from pathlib import Path
import argparse
import ast
import hashlib
import io
import json
import re
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
RELEASE = 'AIR2-P8-M2'
PREFIX = 'AirRemote_TTL_Multi_AIR2_P8_M2_source'
ROOT_DOCS = ('README.md', 'README.zh-CN.md', 'DISCLAIMER.md', 'DISCLAIMER.zh-CN.md',
             'NOTICE.md', 'NOTICE.zh-CN.md', 'LICENSE')
REFERENCE = 'shared/reference/c11_offset_transform.bin'
REFERENCE_SHA256 = '7779d34181f9d302d2d122e9a2ed40f975a4128b738a40561f97fc86ac949303'
# Explicit source closure. Exploration scripts, candidate dumps/listings and
# old PASS reports are deliberately not collected by recursive extension scans.
SHARED_SOURCE = (
    'build_variants.py', 'inspect_variants.py', 'repack_variants.py',
    'runtime_generator.py', 'gesture_runtime_codegen.py', 'record_runtime_codegen.py',
    'persistence_backend.py', 'state_model.py', 'pic18_vm.py',
    'test_integrated_firmware.py', 'tests_core.py', 'test_persistence_backend.py',
    'test_pic18_vm.py', 'test_boot_restore_m2.py', 'test_repack_variants.py',
    'helpers/container.py', 'helpers/reference_codec.py', 'helpers/README.md',
    'reference/codec_manifest.json', 'reference/c11_offset_transform.bin',
    'NATIVE_BACKEND_ABI.md', 'VM_README.zh-CN.md', 'PERSISTENCE_BACKEND.md',
    'RAM_ALLOCATION.zh-CN.md', 'ram_allocation_audit.json',
    'identity_report.md', 'identity_report.json',
    'HSS_PRESERVATION_M2.md', 'HSS_PRESERVATION_M2.json',
    'newGUI_GATE.md', 'newGUI_GATE.json', 'stock_inventory.json',
    'final_validation_m2.json',
)
MODEL_SOURCE = {
    'N': ('native_backend.py', 'native_hooks.py', 'port_profile.json',
          'test_native_backend.py', 'test_native_hooks.py', 'test_full_link.py', 'test_idle_retry_m2.py',
          'PORT_REVIEW.zh-CN.md', 'N_TIMING_AND_NATIVE_ABI.zh-en.md',
          'IDLE_RETRY_M2.md', 'IDLE_RETRY_M2.zh-CN.md'),
    'F': ('native_backend.py', 'native_hooks.py', 'port_profile.json',
          'test_native_backend.py', 'test_integrated_hooks.py', 'test_ui_parity_m2.py',
          'README.md', 'README.zh-CN.md', 'M2_UI_FIX.md', 'M2_UI_FIX.zh-CN.md', 'F_A5_adapter_evidence.json',
          'F_A5_clock_irq_evidence.json'),
    'O': ('native_backend.py', 'native_hooks.py', 'native_contract.py',
          'model_adapter.py', 'port_profile.json',
          'test_native_backend.py', 'test_native_adapter.py',
          'test_model_integration.py', 'test_mode_transition.py', 'test_idle_retry_m2.py',
          'PORT_STATUS.md', 'hook_contract.json', 'hook_review.md',
          'keyboard_contract.json', 'keyboard_review.md',
          'mode_transition_contract.json', 'mode_transition_contract.md',
          'ram_nvm_contract.json', 'ram_nvm_review.md', 'IDLE_RETRY_M2.md', 'IDLE_RETRY_M2.zh-CN.md'),
    'S': ('native_backend.py', 'native_hooks.py', 'port_profile.json',
          'state_adapter.py', 'control_adapter.py', 'lifecycle_adapter.py',
          'sony_native_contract.py', 'radio/fast_empty_queue.py', 'radio/pic18_emit.py',
          'display/display_adapter.py', 'display/canonical_renderer.py',
          'display/canonical_full_renderer.py', 'display/final_display_hook.py',
          'display/keys/native_key_adapter.py',
          'test_state_adapter.py', 'test_control_adapter.py', 'test_lifecycle_adapter.py',
          'verify_linked.py', 'verify_native_nvm.py', 'test_idle_retry_m2.py', 'README.md', 'README.zh-CN.md',
          'sony_nvm_evidence.json', 'radio/context_audit.py', 'radio/context_audit.json',
          'display/README.md', 'display/keys/README.md', 'display/test_page_hint_integration.py',
          'display/PAGE_HINT_M2.md', 'display/PAGE_HINT_M2.zh-CN.md',
          'radio/README.md', 'radio/README.zh-CN.md',
          'radio/CONCURRENCY.md', 'radio/CONCURRENCY.zh-CN.md',
          'radio/concurrency_audit.json'),
}


def source_names():
    names = list(ROOT_DOCS)
    names.extend('shared/' + name for name in SHARED_SOURCE)
    names.extend(('tools/package_source.py', 'tools/package_portable.py'))
    for model, entries in MODEL_SOURCE.items():
        names.extend(model + '/' + name for name in entries)
        names.append('shared/stock/' + model + '/profile.json')
    require(len(names) == len(set(names)), 'Duplicate source allowlist member')
    return tuple(sorted(names))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def collect():
    rows = {}
    for relative in source_names():
        path = PROJECT / relative
        require(path.is_file() and not path.is_symlink(), 'Missing/linked source member: ' + relative)
        require(PROJECT.resolve() in path.resolve().parents, 'Source leaves project: ' + relative)
        data = path.read_bytes()
        if relative == REFERENCE:
            require(len(data) == 73725 and sha(data) == REFERENCE_SHA256,
                    'Codec parameter reference fingerprint mismatch')
        else:
            require(path.suffix.casefold() in ('.py', '.md', '.json') or relative == 'LICENSE',
                    'Non-source file in allowlist: ' + relative)
            text = data.decode('utf-8-sig')
            require(re.search(r'[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]', text) is None,
                    'Private absolute workspace path: ' + relative)
            if path.suffix == '.py':
                ast.parse(text, filename=relative)
                if relative != 'tools/package_source.py':
                    require(re.search(r'AirRemote_TTL_C_AIR2_P8[/\\](?:source|tools)', text) is None,
                            'External Canon source dependency: ' + relative)
                    require('shared_codec_candidate.base4000.bin' not in text,
                            'Exploratory stock dump dependency: ' + relative)
            elif path.suffix == '.json':
                json.loads(text)
        rows[relative] = data
    # All binary firmware is regenerated from the user's separately supplied,
    # hash-pinned stock EXEs. The sole BIN is a derived transform parameter table.
    require([name for name in rows if name.endswith(('.bin', '.exe', '.hex'))] == [REFERENCE],
            'Unexpected binary payload in source archive')
    for relative, data in rows.items():
        require((PROJECT / relative).read_bytes() == data,
                'Source changed while collecting: ' + relative)
    return rows


def make_archive(rows):
    manifest = {'format': 'air2-multi-source-v1', 'release': RELEASE, 'developer': 'Caimankekw',
                'license': 'AGPL-3.0-only for original authored code; see NOTICE.md',
                'vendor_firmware_included': False,
                'source_scope': 'Explicit build/native-adapter/test closure and focused evidence; excludes historical exploration outputs.',
                'source_binary_references': {REFERENCE: REFERENCE_SHA256},
                'files': {name: {'size': len(data), 'sha256': sha(data)} for name, data in sorted(rows.items())}}
    rows = dict(rows)
    rows['source_manifest.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(rows.items()):
            item = zipfile.ZipInfo(PREFIX+'/'+name, date_time=(2026, 10, 15, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            archive.writestr(item, data)
    result = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        require(archive.testzip() is None, 'Archive CRC verification failed')
        require(len(archive.infolist()) == len(rows), 'Archive member count mismatch')
        for name, data in rows.items():
            require(archive.read(PREFIX+'/'+name) == data, 'Archive content mismatch: '+name)
    return result, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Validate source and ZIP in memory; write nothing')
    args = parser.parse_args()
    if not args.check and args.output is None:
        parser.error('--output is required unless --check is selected')
    rows = collect()
    archive, manifest = make_archive(rows)
    if args.check:
        print(json.dumps({'status': 'PASS_SOURCE_ARCHIVE_STRUCTURE', 'files': len(rows),
                          'source_bytes': sum(map(len, rows.values())), 'zip_bytes': len(archive),
                          'source_prefix': PREFIX, 'sha256': sha(archive),
                          'source_binary_references': manifest['source_binary_references'],
                          'archive_written': False, 'vendor_firmware_included': False,
                          'limits': 'Inventory, syntax, reference pins and ZIP integrity; standalone builds require a separate test.'}, indent=2))
        return
    target = args.output.resolve()
    require(not target.exists() or target.read_bytes() == archive, 'Different existing output; nothing overwritten')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with target.open('xb') as handle:
            handle.write(archive)
    print(json.dumps({'path': str(target), 'sha256': sha(archive), 'source_prefix': PREFIX,
                      'files': len(manifest['files']), 'source_binary_references': manifest['source_binary_references']}, indent=2))


if __name__ == '__main__':
    main()
