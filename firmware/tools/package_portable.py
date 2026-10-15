# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Package reviewed AIR2-P8-M2 outputs without executing firmware or updaters.

Python standard library only. --check is read-only; --export writes exclusively
to a new directory. No subprocess, network, USB or device operation is used.
This verifies packaging evidence; it does not prove bootability or RF behavior.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
RELEASE = 'AIR2-P8-M2'
SOURCE_PREFIX = 'AirRemote_TTL_Multi_AIR2_P8_M2_source'
DOCS = ('README.md', 'README.zh-CN.md', 'DISCLAIMER.md',
        'DISCLAIMER.zh-CN.md', 'NOTICE.md', 'NOTICE.zh-CN.md', 'LICENSE')
SCOPES = {'core', 'native_adapter', 'integration', 'hss_preservation', 'persistence_backend'}
CHECKS = ('native_hook_preimages', 'instruction_boundaries', 'private_ram_allocation',
          'native_calling_conventions', 'radio_queue_backpressure',
          'original_hss_paths_preserved', 'persistence_backend',
          'core_policy_tests', 'native_adapter_tests')
# Independent pins for original GUI containers; no profile file can override them.
STOCK = {
    'N': ('C5', 3652240, 2125208, 2437916,
          '4fa0d7c1ae8201910e0586eef30feadb9230e3c30c7b67b8dc4c2d344dea5591', 43648),
    'S': ('A6', 3652240, 2125208, 2437916,
          '707b65d9cb6ea6c320976e5a6244de05b1f0856ab9c7ddc5008fe739337b9737', 44928),
    'F': ('A5', 3652752, 2125432, 2438140,
          '455b3f8eb74c2a598d5bd679d3450e9850860eae8de84362da71edb4896e4e6a', 45792),
    'O': ('A4', 3652752, 2125432, 2438140,
          '80ae4cac56c6bb7c363062d3ed7927373e4b7a907df8abbc2fed6731621a52b5', 44016),
}
IDENTICAL = ('outside_hex_byte_identical', 'header_byte_identical',
             'sparse_hex_layout_identical', 'opaque_unknown_bytes_identical',
             'protected_ranges_byte_identical', 'full_codec_readback_exact',
             'complete_offline_gate_required')
FIXED_ZIP_DATE = (2026, 10, 15, 0, 0, 0)
THIRD_PARTY_SHA256 = '7d41f0e5609df0750aa07c9a1fb3c9cd7d1ce917d7b51c498db212c25854e1ce'


class PackageError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PackageError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def parse_json(data, description):
    try:
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError) as exc:
        raise PackageError('Invalid JSON: ' + description) from exc
    require(isinstance(value, dict), description + ' must be a JSON object')
    return value


def digest(value, name):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value),
            name + ' must be lowercase SHA256')
    return value


def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value and ':' not in value,
            'Unsafe relative path')
    path = PurePosixPath(value)
    require(not path.is_absolute() and str(path) == value and
            all(part not in ('', '.', '..') for part in value.split('/')),
            'Unsafe relative path: ' + value)
    require(not any(ord(char) < 32 for char in value), 'Control character in path')
    return path


def read_file(path, limit=64 * 1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Expected regular input: ' + str(path))
    require(path.stat().st_size <= limit, 'Input exceeds size bound: ' + str(path))
    return path.read_bytes()


def pointer(document, expression):
    require(isinstance(expression, str) and expression.startswith('/'), 'Expected JSON pointer')
    value = document
    try:
        for part in expression[1:].split('/'):
            key = part.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise PackageError('Missing report pointer: ' + expression) from exc
    return value


def parse_hex(data):
    """Independent Intel HEX checksum/layout parser; no codec/build import."""
    memory, shape, upper, ended = {}, [], 0, False
    for line in data.splitlines(keepends=True):
        bare = line.rstrip(b'\r\n')
        ending = line[len(bare):]
        require(not ended and bare.startswith(b':'), 'Invalid Intel HEX record')
        try:
            row = bytes.fromhex(bare[1:].decode('ascii'))
        except (UnicodeError, ValueError) as exc:
            raise PackageError('Invalid Intel HEX encoding') from exc
        require(len(row) >= 5 and len(row) == row[0] + 5 and sum(row) % 256 == 0,
                'Invalid Intel HEX count/checksum')
        require(bare[1:].upper() == row.hex().upper().encode('ascii'), 'Noncanonical HEX record')
        length, address, kind = row[0], int.from_bytes(row[1:3], 'big'), row[3]
        payload = row[4:-1]
        shape.append((length, address, kind, ending,
                      payload if kind != 0 else None))
        if kind == 0:
            require(address + length <= 0x10000, 'HEX record crosses bank')
            for i, byte in enumerate(payload):
                absolute = upper + address + i
                require(absolute not in memory, 'Overlapping HEX records')
                memory[absolute] = byte
        elif kind == 4:
            require(length == 2 and address == 0, 'Invalid HEX upper address')
            upper = int.from_bytes(payload, 'big') << 16
        elif kind == 1:
            require(length == 0 and address == 0, 'Invalid HEX EOF')
            ended = True
        else:
            raise PackageError('Unsupported Intel HEX record type')
    require(ended and memory, 'Missing HEX EOF/data')
    return memory, shape


def plan_ranges(plan, report, tail):
    protected = [(0x4000, 0x4100), (0xF800, 0x20000)]
    extra = plan.get('protected_ranges', [])
    require(isinstance(extra, list) and len(extra) >= 3, 'Missing native protected ranges')
    for row in extra:
        start, end = row.get('start'), row.get('end')
        require(type(start) is int and type(end) is int and 0x4000 <= start < end <= 0x20000,
                'Invalid protected range')
        protected.append((start, end))
    require(any(start <= 0x4108 < end for start, end in protected), 'Unprotected interrupt entry')
    covered, declared = set(), []
    for kind, field in [('hook', 'hooks'), ('section', 'sections')]:
        entries = plan.get(field)
        require(isinstance(entries, list) and entries, 'Missing ' + field)
        for row in entries:
            address = row.get('address')
            try:
                data = bytes.fromhex(row['replacement_hex' if kind == 'hook' else 'data_hex'])
                before = bytes.fromhex(row['expected_hex']) if kind == 'hook' else b'\xff' * len(data)
            except (KeyError, TypeError, ValueError) as exc:
                raise PackageError('Invalid patch bytes') from exc
            require(type(address) is int and data and address % 2 == 0 and len(data) % 2 == 0,
                    'Unaligned/empty patch')
            end = address + len(data)
            require(0x4100 <= address < end <= 0xF800, 'Patch outside code range')
            require(len(before) == len(data), 'Hook preimage length mismatch')
            require(end <= tail if kind == 'hook' else address >= ((tail + 1) & ~1),
                    'Wrong original/additional code boundary')
            require(all(end <= start or address >= stop for start, stop in protected),
                    'Patch intersects protected region')
            positions = set(range(address, end))
            require(not covered.intersection(positions), 'Overlapping patches')
            covered.update(positions)
            declared.append({'kind': kind, 'address': address, 'length': len(data),
                             'role': row.get('role', ''), 'before_sha256': sha(before),
                             'after_sha256': sha(data)})
    require(report.get('patched_ranges') == declared, 'Repack patch list does not match plan')
    return covered, protected


def validate_container(model, original, custom, plan, report):
    revision, size, begin, end, stock_hash, tail = STOCK[model]
    require(len(original) == size and sha(original) == stock_hash, 'Wrong original model/revision EXE')
    require(len(custom) == size and custom != original, 'Wrong custom EXE size or unchanged stock')
    require(custom[:begin] == original[:begin] and custom[end:] == original[end:],
            'Original GUI/loader bytes outside HEX changed')
    require(plan.get('schema_version') == 1 and plan.get('model') == model and
            plan.get('stock_sha256') == stock_hash, 'Wrong patch-plan model/schema/stock')
    require(report.get('model') == model and report.get('stock_sha256') == stock_hash,
            'Wrong repacker model/stock')
    require(report.get('output_sha256') == sha(custom) and
            report.get('output_hex_sha256') == sha(custom[begin:end]), 'Repack output hash mismatch')
    require(report.get('plan_sha256') == sha(json.dumps(plan, sort_keys=True).encode('utf-8')),
            'Canonical patch-plan hash mismatch')
    digest(report.get('output_partial_plaintext_sha256'), 'Final plaintext hash')
    for key in IDENTICAL:
        require(report.get(key) is True, 'Repack gate missing: ' + key)
    for key in ('updater_executed', 'device_accessed', 'device_boot_verified'):
        require(report.get(key) is False, 'Expected offline-only repack field: ' + key)
    for check in CHECKS:
        require(plan.get('validation', {}).get(check) is True and
                report.get('validation', {}).get(check) is True, 'Incomplete validation: ' + check)
    covered, protected = plan_ranges(plan, report, tail)
    stock_memory, stock_shape = parse_hex(original[begin:end])
    new_memory, new_shape = parse_hex(custom[begin:end])
    require(stock_shape == new_shape and stock_memory.keys() == new_memory.keys(),
            'Sparse HEX layout changed')
    changed = {address for address in stock_memory if stock_memory[address] != new_memory[address]}
    require(changed and changed.issubset(covered), 'Undeclared encrypted data changed')
    for start, stop in protected:
        require(not any(start <= address < stop for address in changed), 'Protected wire data changed')
    require(type(report.get('changed_plaintext_byte_count')) is int and
            0 < report['changed_plaintext_byte_count'] <= len(covered), 'Invalid changed-byte evidence')
    return {'original_revision': revision, 'changed_wire_bytes': len(changed),
            'declared_patch_bytes': len(covered), 'outside_hex_byte_identical': True,
            'declared_wire_only': True, 'header_reserved_and_opaque_bytes_identical': True}


def validate_source(archive, readiness, docs, own_source):
    prefix = readiness.get('source_prefix')
    require(len(safe_relative(prefix).parts) == 1, 'Source ZIP requires one top-level directory')
    require(prefix == SOURCE_PREFIX, 'Wrong source release prefix')
    expected_references = readiness.get('source_binary_references', {})
    require(isinstance(expected_references, dict), 'Invalid source reference whitelist')
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise PackageError('Invalid source ZIP') from exc
    with zf:
        rows, seen, expanded = {}, set(), 0
        for info in zf.infolist():
            require(not info.is_dir(), 'Source ZIP must list files only')
            path = safe_relative(info.filename)
            require(path.parts[0] == prefix and len(path.parts) > 1, 'Unexpected source root')
            folded = info.filename.casefold()
            require(folded not in seen, 'Duplicate/case-colliding source ZIP member')
            seen.add(folded)
            require(not stat.S_ISLNK(info.external_attr >> 16), 'Source symlink not allowed')
            require(not info.flag_bits & 1, 'Encrypted source ZIP not allowed')
            expanded += info.file_size
            require(info.file_size <= 16 * 1024 * 1024 and expanded <= 64 * 1024 * 1024,
                    'Source ZIP size exceeds bound')
            relative = '/'.join(path.parts[1:])
            parts = [part.casefold() for part in path.parts[1:]]
            require(not any(part in {'build', 'dist', 'release', '.git', '__pycache__',
                                     'captures', 'capture', 'credentials', 'tokens'} for part in parts),
                    'Source archive contains outputs/private data: ' + relative)
            require(not any(part == '.env' or part.startswith('.env.') or
                            part in {'token.json', 'tokens.json', 'credentials.json', 'cookies.json'}
                            for part in parts), 'Private source member: ' + relative)
            suffix = PurePosixPath(relative).suffix.casefold()
            require(suffix not in {'.exe', '.dll', '.zip', '.7z', '.arw', '.jpg', '.jpeg',
                                   '.pcap', '.pcapng', '.pyc', '.pem', '.key', '.pfx', '.tmp', '.bak'},
                    'Forbidden source ZIP artifact: ' + relative)
            data = zf.read(info)
            if suffix in {'.bin', '.hex'}:
                require(expected_references.get(relative) == sha(data),
                        'Unreviewed source binary reference: ' + relative)
            rows[relative] = data
        require('source_manifest.json' in rows, 'Missing source_manifest.json')
        manifest_data = rows.pop('source_manifest.json')
        manifest = parse_json(manifest_data, 'source manifest')
        require(manifest.get('release') == RELEASE, 'Wrong source manifest release')
        files = manifest.get('files')
        require(isinstance(files, dict) and set(files) == set(rows), 'Source manifest inventory mismatch')
        for name, data in rows.items():
            require(files[name] == {'size': len(data), 'sha256': sha(data)}, 'Source manifest mismatch: ' + name)
        for name, data in dict(docs, **{'tools/package_portable.py': own_source}).items():
            require(rows.get(name) == data, 'Source ZIP differs from current package source: ' + name)
        require(set(expected_references).issubset(rows), 'Unknown source binary reference entry')
        require(readiness.get('source_dependency_closure_reviewed') is True,
                'Source dependency closure has not been reviewed')
        return {'sha256': sha(archive), 'files': len(rows), 'prefix': prefix,
                'manifest_sha256': sha(manifest_data),
                'dependency_closure_reviewed': True}


def validate_reports(readiness, base, image_hash, plan):
    entries = readiness.get('validation_reports')
    require(isinstance(entries, list) and entries, 'No final-image reports')
    covered, summaries, report_hashes = set(), [], set()
    for entry in entries:
        relative = str(safe_relative(entry.get('path')))
        resolved = (base / relative).resolve()
        require(base == resolved or base in resolved.parents, 'Report leaves readiness directory')
        data = read_file(resolved, 4 * 1024 * 1024)
        expected_hash = digest(entry.get('sha256'), 'Report hash')
        require(sha(data) == expected_hash, 'Report hash mismatch: ' + relative)
        report = parse_json(data, relative)
        outcome = pointer(report, entry.get('pass_pointer'))
        expected_pass = entry.get('pass_value')
        require(expected_pass is True or
                (isinstance(expected_pass, str) and expected_pass.startswith('PASS')),
                'Report pass value must be true or a PASS status')
        require(type(outcome) is type(expected_pass) and outcome == expected_pass,
                'Report has not passed: ' + relative)
        require(pointer(report, entry.get('image_sha256_pointer')) == image_hash,
                'Report does not validate the actual final plaintext: ' + relative)
        scopes = entry.get('scopes')
        require(isinstance(scopes, list) and scopes and set(scopes).issubset(SCOPES),
                'Invalid report scopes')
        if 'persistence_backend' in scopes:
            enabled = pointer(report, entry.get('nv_enabled_pointer'))
            require(type(enabled) is bool and enabled == readiness['nv_enabled'],
                    'Persistence report disagrees with readiness')
        covered.update(scopes)
        report_hashes.add(expected_hash)
        summaries.append({'source_file': relative, 'sha256': expected_hash, 'pass_value': outcome,
                          'image_sha256': image_hash, 'scopes': sorted(scopes)})
    require(covered == SCOPES, 'Missing final-image verification scopes: ' + ', '.join(sorted(SCOPES - covered)))
    require(plan.get('verification_report_sha256') in report_hashes,
            'Plan is not bound to a supplied passing final-image report')
    return summaries


def prepare(args):
    model = args.model
    require(model in STOCK, 'Unsupported model')
    output = Path(args.output).resolve()
    require(not output.exists(), 'Output path already exists; nothing overwritten')
    custom, original = read_file(args.updater), read_file(args.original)
    notices_path = args.third_party_notices or Path(args.original).parent / 'license_3rd_party.txt'
    third_party = read_file(notices_path, 4 * 1024 * 1024)
    require(sha(third_party) == THIRD_PARTY_SHA256, 'Original third-party notices fingerprint mismatch')
    plan_data, repack_data = read_file(args.plan), read_file(args.repack_report)
    ready_data, archive = read_file(args.readiness), read_file(args.source_archive, 32 * 1024 * 1024)
    plan, repack = parse_json(plan_data, 'patch plan'), parse_json(repack_data, 'repack report')
    ready = parse_json(ready_data, 'readiness')
    require(ready.get('format') == 'multi-air2-portable-readiness-v1' and
            ready.get('status') == 'OFFLINE_VALIDATED_EXPERIMENTAL' and
            ready.get('release') == RELEASE and ready.get('model') == model, 'Wrong/unvalidated readiness')
    require(type(ready.get('nv_enabled')) is bool and ready.get('unresolved_imports') == [],
            'Unresolved native backend or missing NVM status')
    require(type(ready.get('export_authorized')) is bool, 'Missing explicit export gate')
    require(not args.export or ready['export_authorized'], 'Final reviewed export is not authorized')
    own_source = read_file(Path(__file__))
    docs = {name: read_file(ROOT / name, 1024 * 1024) for name in DOCS}
    actual = {'candidate_sha256': sha(custom), 'stock_sha256': sha(original),
              'plan_file_sha256': sha(plan_data), 'repack_report_sha256': sha(repack_data),
              'source_archive_sha256': sha(archive), 'packager_sha256': sha(own_source),
              'third_party_notices_sha256': sha(third_party)}
    for name, value in actual.items():
        require(digest(ready.get(name), name) == value, 'Readiness hash mismatch: ' + name)
    require(ready.get('docs_sha256') == {name: sha(data) for name, data in docs.items()},
            'Documents differ from reviewed readiness')
    if 'plan_file_sha256' in repack:
        require(repack['plan_file_sha256'] == sha(plan_data), 'Repacker raw plan hash mismatch')
    if 'verification_report_sha256' in repack:
        require(repack['verification_report_sha256'] == plan.get('verification_report_sha256'),
                'Repacker verification binding mismatch')
    container = validate_container(model, original, custom, plan, repack)
    reports = validate_reports(ready, Path(args.readiness).resolve().parent,
                               repack['output_partial_plaintext_sha256'], plan)
    source = validate_source(archive, ready, docs, own_source)
    name = 'Air-Remote-TTL-%s-%s' % (model, RELEASE)
    payload = dict(docs)
    payload[name + '.exe'] = custom
    payload['restore_original/Air-Remote-TTL-%s-Firmware-%s.exe' % (model, STOCK[model][0])] = original
    payload['source.zip'] = archive
    payload['licenses/license_3rd_party.txt'] = third_party
    nv_en = 'Enabled; power-loss and reboot hardware testing remains required.' if ready['nv_enabled'] else 'Disabled; this build does not claim settings survive power-off.'
    nv_zh = '已启用；断电与重启仍需实机验证。' if ready['nv_enabled'] else '未启用；此版本不承诺断电后保存设置。'
    payload['PACKAGE.md'] = ("# %s\n\nDeveloper / 开发者: Caimankekw\n\n"
        "Offline-validated experimental package; hardware startup, RF delivery and exposure are not certified.\n"
        "离线校验实验包；尚不代表真机启动、无线送达或曝光已通过。\n\n"
        "Target / 适用型号: Air Remote TTL-%s, original %s. Never mix mounts / 禁止混用其他接口型号。\n\n"
        "Persistence / 参数保存: %s %s\n\n"
        "Extract everything, read README and disclaimers, then manually open `%s.exe`. No installer or automatic flash is provided.\n"
        "完整解压并阅读说明与免责声明，再手动打开对应 EXE 图形界面；本包不自动刷写。\n\n"
        "The unmodified recovery GUI is in `restore_original/`; recovery is not guaranteed.\n"
        "原厂恢复工具位于 `restore_original/`，不保证所有故障均可恢复。\n\n"
        "`source.zip` is the corresponding reviewed source snapshot. AGPL applies to authored work only; see NOTICE.\n"
        "`source.zip` 为对应源码快照；AGPL 仅覆盖原创部分，第三方条款见 NOTICE。\n\n"
        "Custom GUI SHA256: `%s`\n\nFinal partial image SHA256: `%s`\n\nSource ZIP SHA256: `%s`\n"
        % (name, model, STOCK[model][0], nv_en, nv_zh, name, sha(custom),
           repack['output_partial_plaintext_sha256'], sha(archive))).encode('utf-8')
    evidence = {'format': 'multi-air2-portable-evidence-v1', 'model': model, 'release': RELEASE,
                'status': 'PASS_OFFLINE_PACKAGE_EVIDENCE', 'nv_enabled': ready['nv_enabled'],
                'readiness_sha256': sha(ready_data), 'inputs': actual, 'container': container,
                'source_archive': source, 'reports': reports,
                'final_partial_plaintext_sha256': repack['output_partial_plaintext_sha256'],
                'updater_executed': False, 'device_accessed': False, 'device_boot_verified': False,
                'limits': 'Readiness/report binding and container checks; not hardware or RF acceptance.'}
    # Compact, normalized evidence avoids leaking absolute developer paths from raw reports.
    payload['verification/package_evidence.json'] = json_bytes(evidence)
    payload['package_manifest.json'] = json_bytes({'model': model, 'release': RELEASE,
        'developer': 'Caimankekw', 'files': {key: {'size': len(value), 'sha256': sha(value)}
                                          for key, value in sorted(payload.items())}})
    payload['SHA256SUMS.txt'] = ''.join('%s  %s\n' % (sha(value), key)
                                      for key, value in sorted(payload.items())).encode('utf-8')
    return output, name, payload, evidence


def export_package(output, name, payload):
    """Writes only new files. A failed build is retained for inspection."""
    output.mkdir(parents=True, exist_ok=False)
    folder = output / name
    folder.mkdir(exist_ok=False)
    for relative, data in sorted(payload.items()):
        path = folder.joinpath(*safe_relative(relative).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        require(path.read_bytes() == data, 'Written payload comparison failed')
    archive_path = output / (name + '-Portable.zip')
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in sorted(payload.items()):
            info = zipfile.ZipInfo(name + '/' + relative, FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data)
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, 'Portable ZIP CRC failed')
        require(set(archive.namelist()) == {name + '/' + key for key in payload}, 'ZIP inventory mismatch')
        for relative, data in payload.items():
            require(archive.read(name + '/' + relative) == data, 'ZIP byte comparison failed')
    return {'zip': str(archive_path), 'zip_sha256': sha(archive_path.read_bytes()),
            'zip_size': archive_path.stat().st_size, 'payload_files': len(payload),
            'status': 'PASS_OFFLINE_PORTABLE_PACKAGE', 'updater_executed': False, 'device_accessed': False}


def schema():
    return {'format': 'multi-air2-portable-readiness-v1', 'status': 'OFFLINE_VALIDATED_EXPERIMENTAL',
            'release': RELEASE, 'model': 'N', 'candidate_sha256': '<custom EXE sha256>',
            'stock_sha256': STOCK['N'][4], 'plan_file_sha256': '<raw plan file sha256>',
            'repack_report_sha256': '<raw repack report sha256>',
            'source_archive_sha256': '<source ZIP sha256>', 'packager_sha256': '<this script sha256>',
            'third_party_notices_sha256': THIRD_PARTY_SHA256,
            'docs_sha256': {name: '<raw file sha256>' for name in DOCS},
            'source_prefix': SOURCE_PREFIX, 'source_dependency_closure_reviewed': True,
            'source_binary_references': {}, 'nv_enabled': False, 'unresolved_imports': [],
            'export_authorized': False, 'validation_reports': [{
                'path': 'final_image_verification.json', 'sha256': '<raw report file sha256>',
                'pass_pointer': '/status', 'pass_value': 'PASS_FINAL_IMAGE',
                'image_sha256_pointer': '/target_sha256', 'scopes': sorted(SCOPES),
                'nv_enabled_pointer': '/nv_enabled'}],
            '_notes': ['Reports must be below the readiness directory, with POSIX relative paths.',
                       'Every report must bind the repacker final partial-plaintext SHA256.',
                       'One supplied report hash must match plan.verification_report_sha256.',
                       'Source ZIP has one prefix, source_manifest.json files{relative:{size,sha256}};',
                       'manifest excludes itself. All other files must be listed exactly.',
                       'Source must include all seven docs and tools/package_portable.py byte-exact.',
                       'BIN/HEX source references require a relative-path SHA whitelist.',
                       'No modified EXE, opaque original EXE, output tree, captures or credentials in source.',
                       'Final report status and export gate are review inputs, never hardware claims.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', action='store_true')
    parser.add_argument('--model', choices=tuple(STOCK))
    parser.add_argument('--third-party-notices', type=Path,
                        help='Original license_3rd_party.txt; defaults beside --original')
    for option in ('updater', 'original', 'plan', 'repack-report', 'readiness', 'source-archive', 'output'):
        parser.add_argument('--' + option, type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true')
    group.add_argument('--export', action='store_true')
    args = parser.parse_args(argv)
    if args.schema:
        print(json_bytes(schema()).decode('utf-8'))
        return 0
    for option in ('model', 'updater', 'original', 'plan', 'repack_report', 'readiness', 'source_archive', 'output'):
        if getattr(args, option) is None:
            parser.error('--' + option.replace('_', '-') + ' is required')
    try:
        output, name, payload, evidence = prepare(args)
        result = export_package(output, name, payload) if args.export else {
            'status': 'PASS_IN_MEMORY_PACKAGE_PREPARATION', 'model': args.model,
            'candidate_sha256': evidence['inputs']['candidate_sha256'],
            'payload_files': len(payload), 'files_written': False,
            'updater_executed': False, 'device_accessed': False}
        print(json_bytes(result).decode('utf-8'))
    except (PackageError, OSError, zipfile.BadZipFile) as exc:
        print('Packaging refused: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
