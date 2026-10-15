# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Build one model-locked AIR2-P8-M2 Windows wrapper offline; never execute it."""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.util
import io
import json
import re
import struct
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERSION_NAME = 'AIR2-P8-M2'
MODELS = {'N': ('Nikon', 'C5'), 'S': ('Sony', 'A6'), 'F': ('Fujifilm', 'A5'), 'O': ('Olympus', 'A4')}
ROOT_DOCS = ('LICENSE', 'NOTICE.md', 'NOTICE.zh-CN.md', 'DISCLAIMER.md', 'DISCLAIMER.zh-CN.md',
             'CHANGELOG.md', 'CHANGELOG.zh-CN.md')
NSIS_COMPONENTS = {
    '$PLUGINSDIR/LangDLL.dll': 'Plugins/x86-unicode/LangDLL.dll',
    '$PLUGINSDIR/System.dll': 'Plugins/x86-unicode/System.dll',
    '$PLUGINSDIR/nsDialogs.dll': 'Plugins/x86-unicode/nsDialogs.dll',
    '$PLUGINSDIR/modern-wizard.bmp': 'Contrib/Graphics/Wizard/win.bmp',
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(data):
    return {'size': len(data), 'sha256': sha(data)}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def pinned(data, digest, label):
    need(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid SHA256 pin: ' + label)
    need(sha(data) == digest, 'Input fingerprint differs: ' + label)
    return data


def safe_relative(name):
    need(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'Invalid relative path')
    parts = PurePosixPath(name)
    need(not parts.is_absolute() and all(p not in ('', '.', '..') for p in name.split('/')),
         'Unsafe relative path: ' + name)
    return parts


def regular_files(directory):
    need(directory.is_dir() and not directory.is_symlink(), 'Input directory missing or symlink')
    files = {}
    for path in sorted(directory.rglob('*')):
        need(not path.is_symlink(), 'Symbolic links are not accepted')
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = path.read_bytes()
    return files


def load_profile():
    profile = json.loads((ROOT / 'release_profile.json').read_text(encoding='utf-8'))
    model = json.loads((ROOT / 'model.json').read_text(encoding='utf-8'))
    validate_profile(profile, model)
    return profile, model


def validate_profile(profile, model):
    need(profile.get('schema') == 'airremote-air2-release-profile-v1', 'Release profile schema')
    tag = profile.get('model')
    need(tag in MODELS, 'Unsupported target model')
    brand, stock_revision = MODELS[tag]
    need(profile.get('brand') == brand and profile.get('stock_revision') == stock_revision,
         'Target brand/stock revision mismatch')
    need(profile.get('version') == VERSION_NAME and profile.get('product_version') == '8.0.2.0',
         'Target release version mismatch')
    need(profile.get('name_slug') == 'AirRemote_TTL_' + tag + '_AIR2_P8_M2', 'Source name mismatch')
    need(profile.get('inner_exe_name') == 'Air-Remote-TTL-' + tag + '-AIR2-P8-M2.exe', 'Inner updater name')
    for key in ('branch', 'tag'):
        need(isinstance(profile.get(key), str) and re.fullmatch('[a-zA-Z0-9._-]+', profile[key]),
             'Unsafe release ' + key)
    need(re.fullmatch(r'\d{4}-\d{2}-\d{2}', profile.get('release_date', '2026-10-16')), 'Release date')
    need(model.get('model') == 'Air Remote TTL-' + tag and model.get('version') == stock_revision,
         'Stock model identity mismatch')
    for digest in (profile['expected']['image_sha256'], profile['expected']['exe_sha256'], model['source_sha256']):
        need(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid profile SHA256')
    return profile


def parse_source_archive(data, expected_sha):
    # One shared parser verifies every source entry, its model identity and all frozen firmware pins.
    path = ROOT / 'tools/package_source.py'
    spec = importlib.util.spec_from_file_location('air2_branch_source_packager', path)
    need(spec is not None and spec.loader is not None, 'Source archive validator unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files, manifest = module.parse_archive(data, expected_sha)
    files = dict(files)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        entries = [name for name in source.namelist() if name.count('/') == 1 and name.endswith('/source_manifest.json')]
        need(len(entries) == 1, 'Source manifest root mismatch')
        files['source_manifest.json'] = source.read(entries[0])
    return files, manifest


def validate_source_archive(data, expected_sha, profile, model):
    files, manifest = parse_source_archive(data, expected_sha)
    need(manifest.get('format') == 'airremote-air2-branch-source-v1'
         and manifest.get('model') == profile['model'] and manifest.get('name') == VERSION_NAME
         and manifest.get('branch') == profile['branch'] and manifest.get('release_tag') == profile['tag'],
         'Source archive belongs to another release/model')
    need(all(name in files for name in ROOT_DOCS), 'Source root license/disclaimer documents missing')
    current = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in HERE.rglob('*')
               if p.is_file() and not {'build', 'dist', '__pycache__'} & set(p.relative_to(HERE).parts)}
    archived = {name: blob for name, blob in files.items() if name.startswith('windows/')}
    need(archived == current, 'Archived Windows source differs from the current source tree')
    for name in ROOT_DOCS + ('model.json', 'release_profile.json', 'tools/package_source.py'):
        need(files[name] == (ROOT / name).read_bytes(), 'Source root document/profile differs: ' + name)
    return files


def product_name(profile):
    return 'Air Remote TTL-' + profile['model'] + ' AIR2-P8-M2 Custom Updater'


def render_template(blob, profile, model):
    values = {'MODEL': profile['model'], 'BRAND': profile['brand'], 'STOCK_REVISION': profile['stock_revision'],
              'TAG': profile['tag'], 'BRANCH': profile['branch'], 'UPDATER_NAME': profile['inner_exe_name'],
              'RELEASE_DATE': profile.get('release_date', '2026-10-16'),
              'UPDATER_SHA256': profile['expected']['exe_sha256'],
              'IMAGE_SHA256': profile['expected']['image_sha256']}
    text = blob.decode('utf-8')
    for name, value in values.items():
        text = text.replace('@' + name + '@', value)
    need(re.search(r'@[A-Z_0-9]+@', text) is None, 'Unresolved README template field')
    return text.encode('utf-8')


def pe_resources(data):
    """Read PE headers and leaf resources without loading the executable."""
    def unpack(fmt, offset):
        need(0 <= offset <= len(data) - struct.calcsize(fmt), 'PE structure outside input')
        return struct.unpack_from(fmt, data, offset)
    need(data[:2] == b'MZ', 'PE MZ signature missing')
    nt = unpack('<I', 0x3C)[0]
    need(data[nt:nt + 4] == b'PE\0\0', 'PE signature missing')
    machine, count, _, _, _, optional_size, _ = unpack('<HHIIIHH', nt + 4)
    need(machine in (0x14C, 0x8664) and 1 <= count <= 96, 'PE machine or section count')
    opt = nt + 24
    magic = unpack('<H', opt)[0]
    need(magic in (0x10B, 0x20B), 'PE optional header magic')
    directory = opt + (96 if magic == 0x10B else 112)
    need(optional_size >= directory - opt + 8 * 5, 'PE optional header too short')
    resources_rva, resources_size = unpack('<II', directory + 8 * 2)
    certificate_offset, certificate_size = unpack('<II', directory + 8 * 4)
    sections = []
    for index in range(count):
        header = opt + optional_size + 40 * index
        _, virtual_size, rva, raw_size, raw, _, _, _, _, _ = unpack('<8sIIIIIIHHI', header)
        need(raw <= len(data) and raw_size <= len(data) - raw, 'PE section outside input')
        sections.append((rva, max(virtual_size, raw_size), raw, raw_size))
    def file_offset(rva, size):
        for base, _, raw, raw_size in sections:
            if base <= rva and rva - base + size <= raw_size:
                return raw + rva - base
        raise ValueError('PE resource RVA outside section')
    need(resources_size > 0, 'PE resources missing')
    resource_base = file_offset(resources_rva, resources_size)
    leaves = []
    visited = set()
    def walk(relative, path):
        need(len(path) <= 3 and relative not in visited, 'PE resource cycle/depth')
        visited.add(relative)
        need(relative + 16 <= resources_size, 'PE resource directory outside bounds')
        named, ids = unpack('<HH', resource_base + relative + 12)
        need(relative + 16 + 8 * (named + ids) <= resources_size, 'PE resource entries outside bounds')
        for index in range(named + ids):
            key, target = unpack('<II', resource_base + relative + 16 + 8 * index)
            name = key
            if key & 0x80000000:
                pos = key & 0x7FFFFFFF
                need(pos + 2 <= resources_size, 'PE resource name bounds')
                size = unpack('<H', resource_base + pos)[0] * 2
                need(pos + 2 + size <= resources_size, 'PE resource name outside bounds')
                name = data[resource_base + pos + 2:resource_base + pos + 2 + size].decode('utf-16le')
            offset = target & 0x7FFFFFFF
            if target & 0x80000000:
                walk(offset, path + (name,))
            else:
                need(offset + 16 <= resources_size, 'PE leaf entry outside bounds')
                rva, size, _, _ = unpack('<IIII', resource_base + offset)
                start = file_offset(rva, size)
                leaves.append((path + (name,), data[start:start + size]))
    walk(0, ())
    return {'machine': machine, 'certificate_offset': certificate_offset,
            'certificate_size': certificate_size, 'resources': leaves}


def version_strings(data):
    result = {}
    def node(start, limit, depth):
        need(depth <= 4 and start + 6 <= limit, 'PE version structure bounds/depth')
        length, value_length, kind = struct.unpack_from('<HHH', data, start)
        end = start + length
        need(length >= 6 and end <= limit and kind in (0, 1), 'PE version block length/type')
        pos = start + 6
        key_start = pos
        while pos + 2 <= end and data[pos:pos + 2] != b'\0\0':
            pos += 2
        need(pos + 2 <= end, 'PE version key terminator')
        key = data[key_start:pos].decode('utf-16le')
        value_start = (pos + 2 + 3) & ~3
        size = value_length * (2 if kind == 1 else 1)
        need(value_start + size <= end, 'PE version value bounds')
        if depth == 3:
            need(kind == 1 and key not in result, 'PE version string type/duplicate')
            result[key] = data[value_start:value_start + size].decode('utf-16le').rstrip('\0')
        child = (value_start + size + 3) & ~3
        while child + 6 <= end:
            child = (node(child, end, depth + 1) + 3) & ~3
        return end
    need(node(0, len(data), 0) == len(data), 'PE version trailing bytes')
    return result


def verify_installer_pe(data, profile):
    pe = pe_resources(data)
    need(pe['certificate_offset'] == 0 and pe['certificate_size'] == 0, 'Unexpected wrapper signature')
    manifests = [blob for path, blob in pe['resources'] if path[0] == 24]
    need(len(manifests) == 1, 'One wrapper manifest required')
    text = manifests[0].decode('utf-8-sig')
    need(re.search(r'<requestedExecutionLevel\s+[^>]*level="asInvoker"', text) is not None,
         'Wrapper must be asInvoker')
    need('requireAdministrator' not in text, 'Unexpected wrapper elevation')
    versions = [blob for path, blob in pe['resources'] if path[0] == 16]
    need(len(versions) == 1, 'One version resource required')
    values = version_strings(versions[0])
    need(values.get('CompanyName') == 'Caimankekw', 'Wrapper developer attribution missing')
    need(values.get('ProductName') == product_name(profile), 'Wrapper product identity missing')
    return {'machine': hex(pe['machine']), 'as_invoker': True, 'authenticode_signed': False,
            'developer': 'Caimankekw'}


def preflight(args):
    pins = json.loads((HERE / 'input_manifest.json').read_text(encoding='utf-8'))
    need(pins.get('format') == 'air2-m2-windows-tools-v1', 'Input manifest identity mismatch')
    profile, model = load_profile()
    updater = pinned(args.updater.read_bytes(), profile['expected']['exe_sha256'], 'model AIR2-P8-M2 updater')
    original = pinned(args.original.read_bytes(), model['source_sha256'], 'model original updater')
    need(len(original) == model['source_size'], 'Original updater size differs')
    vendor_notice = pinned(args.vendor_notice.read_bytes(), pins['vendor_notice_sha256'], 'vendor third-party notice')
    source = args.source_archive.read_bytes()
    source_files = validate_source_archive(source, args.source_sha256, profile, model)
    pe_resources(updater)
    pe_resources(original)
    nsis = regular_files(args.nsis_dir)
    inventory = {name: record(blob) for name, blob in sorted(nsis.items())}
    tree = json.dumps(inventory, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    need(len(nsis) == pins['nsis']['tree_files'] and sha(tree) == pins['nsis']['tree_sha256'],
         'Complete NSIS 3.13 directory fingerprint differs')
    for name in ('7z.exe', '7z.dll'):
        path = args.seven_zip if name == '7z.exe' else args.seven_zip.parent / name
        pinned(path.read_bytes(), pins['seven_zip'][name], name)
    copying = pinned((HERE / 'vendor/NSIS-COPYING.txt').read_bytes(), pins['nsis']['copying_sha256'], 'NSIS license')
    need(copying == nsis['COPYING'], 'NSIS license source differs')
    return updater, original, source, source_files, nsis, pins, profile, model, vendor_notice


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    need(path.read_bytes() == data, 'Write mismatch: ' + path.name)


def execute(argv, cwd, log, timeout):
    process = subprocess.run([str(v) for v in argv], cwd=cwd, shell=False, capture_output=True,
                             encoding='utf-8', errors='replace', timeout=timeout)
    write_new(log, (process.stdout + process.stderr).encode('utf-8'))
    need(process.returncode == 0, 'Compiler/archive check failed; see ' + log.name)


def build_package(args):
    updater, original, source, source_files, nsis, pins, profile, model, vendor_notice = preflight(args)
    package_name = 'AirRemote-TTL-' + profile['model'] + '-AIR2-P8-M2'
    installer_name = 'Profoto-' + package_name + '-Custom-Updater.exe'
    updater_name = profile['inner_exe_name']
    original_name = 'Air-Remote-TTL-' + profile['model'] + '-Firmware-' + profile['stock_revision'] + '.exe'
    output = args.output.resolve()
    need(not output.exists(), 'Output exists; choose a new directory')
    for path in (args.updater, args.original, args.vendor_notice, args.source_archive, args.nsis_dir, args.seven_zip.parent):
        need(output != path and output not in path.parents and path not in output.parents,
             'Output overlaps an input')
    files = {updater_name: updater, 'restore_original/' + original_name: original, 'source.zip': source,
             'NSIS-COPYING.txt': nsis['COPYING'], 'license_3rd_party.txt': vendor_notice}
    files.update({name: source_files[name] for name in ROOT_DOCS})
    for name in ('README.md', 'README.zh-CN.md'):
        files[name] = render_template((HERE / 'templates' / name).read_bytes(), profile, model)
    manifest = {'format': 'air2-m2-windows-package-v1', 'model': profile['model'], 'brand': profile['brand'], 'name': VERSION_NAME,
                'release_date': profile.get('release_date', '2026-10-16'), 'release_tag': profile['tag'], 'developer': 'Caimankekw',
                'authored_source_license': 'AGPL-3.0-only', 'firmware_unchanged_by_packaging': True,
                'expected_firmware_image_sha256': profile['expected']['image_sha256'],
                'updater_sha256': sha(updater), 'original_sha256': sha(original),
                'source_archive_sha256': sha(source), 'source_tree_sha256': sha(source_files['source_manifest.json']),
                'builder_sha256': sha(Path(__file__).read_bytes()),
                'nsis_script_sha256': sha((HERE / 'installer.nsi').read_bytes()),
                'input_manifest_sha256': sha((HERE / 'input_manifest.json').read_bytes()),
                'files': {name: record(blob) for name, blob in sorted(files.items())},
                'hardware_validated_by_packaging': False, 'm2_hardware_validated': False}
    files['package_manifest.json'] = encoded(manifest)
    files['SHA256SUMS.txt'] = ''.join(sha(blob) + '  ' + name + '\n'
                                    for name, blob in sorted(files.items())).encode('ascii')
    # Validate source/data before creating any output directory.
    for private in (str(ROOT), str(Path.home())):
        for marker in (private.encode('utf-8'), private.encode('utf-16le')):
            need(all(marker not in blob for blob in files.values()), 'Private path in package payload')
    output.mkdir(parents=True, exist_ok=False)
    package = output / package_name
    for name, blob in sorted(files.items()):
        safe_relative(name)
        write_new(package / name, blob)
    for original_name, display_name in (('LICENSE', 'LICENSE.txt'), ('DISCLAIMER.md', 'DISCLAIMER.en.txt'),
                                        ('DISCLAIMER.zh-CN.md', 'DISCLAIMER.zh-CN.txt')):
        text = source_files[original_name].decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        write_new(output / 'installer_text' / display_name, b'\xff\xfe' + text.replace('\n', '\r\n').encode('utf-16le'))
    archive = output / (package_name + '-Windows-portable.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, blob in sorted(files.items()):
            entry = zipfile.ZipInfo(package_name + '/' + name, (2026, 10, 16, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            zipped.writestr(entry, blob)
    with zipfile.ZipFile(archive) as zipped:
        need(zipped.testzip() is None and len(zipped.namelist()) == len(files), 'Portable ZIP CRC/inventory')
        need(set(zipped.namelist()) == {package_name + '/' + name for name in files}, 'Portable ZIP names')
        need(all(zipped.read(package_name + '/' + name) == blob for name, blob in files.items()), 'Portable ZIP bytes')
    installer = output / installer_name
    execute([args.nsis_dir / 'makensis.exe', '/NOCD', '/V3', '/INPUTCHARSET', 'UTF8', '/DOUTPUT_EXE=' + installer.name,
             '/DPACKAGE_DIR=' + package_name, '/DTEXT_DIR=installer_text',
             '/DMODEL=' + profile['model'], '/DBRAND=' + profile['brand'],
             '/DSTOCK_REVISION=' + profile['stock_revision'], '/DUPDATER_NAME=' + updater_name,
             '/DRELEASE_DATE=' + profile.get('release_date', '2026-10-16'), HERE / 'installer.nsi'],
            output, output / 'logs/nsis_compile.log', 300)
    execute([args.seven_zip, 'x', '-y', '-o' + str(output / 'installer_roundtrip'), installer],
            output, output / 'logs/installer_extract.log', 120)
    extracted = regular_files(output / 'installer_roundtrip')
    need(all(extracted.get(name) == blob for name, blob in files.items()), 'Installer payload byte mismatch')
    need(set(extracted) - set(files) == set(NSIS_COMPONENTS), 'Unexpected embedded installer components')
    for name, relative in NSIS_COMPONENTS.items():
        need(extracted[name] == nsis[relative], 'NSIS embedded component mismatch: ' + name)
    blob = installer.read_bytes()
    pe = verify_installer_pe(blob, profile)
    for private in (str(ROOT), str(Path.home())):
        need(private.encode('utf-8') not in blob and private.encode('utf-16le') not in blob,
             'Private path in installer')
    need(args.updater.read_bytes() == updater and args.original.read_bytes() == original
         and args.source_archive.read_bytes() == source, 'Input changed during packaging')
    report = {'status': 'PASS_WINDOWS_STATIC_PACKAGE', 'name': VERSION_NAME, 'model': profile['model'],
              'release_date': profile.get('release_date', '2026-10-16'), 'release_tag': profile['tag'], 'developer': 'Caimankekw',
              'updater': record(updater), 'original': record(original), 'source_archive': record(source),
              'installer': {'name': installer.name, **record(blob)},
              'portable_zip': {'name': archive.name, **record(archive.read_bytes())},
              'payload_files': len(files), 'installer_pe': pe, 'source_manifest_exact': True,
              'windows_source_matches_archive': True, 'installer_payload_roundtrip': True,
              'portable_zip_roundtrip': True, 'all_input_pins_verified': True,
              'gui_default_launch': False, 'updater_executed': False, 'installer_executed': False,
              'usb_accessed': False, 'drivers_installed': False,
              'runtime_firmware_modified': False, 'm2_hardware_validated': False,
              'outer_exe_byte_reproducibility_claimed': False}
    write_new(output / 'package_verification.json', encoded(report))
    write_new(output / 'SHA256SUMS.txt', (sha(blob) + '  ' + installer.name + '\n' +
              sha(archive.read_bytes()) + '  ' + archive.name + '\n').encode('ascii'))
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--updater', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--vendor-notice', type=Path, required=True)
    parser.add_argument('--source-archive', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--nsis-dir', type=Path, required=True)
    parser.add_argument('--seven-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=HERE / 'build' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))
    args = parser.parse_args()
    for name in ('updater', 'original', 'vendor_notice', 'source_archive', 'nsis_dir', 'seven_zip', 'output'):
        setattr(args, name, getattr(args, name).resolve())
    try:
        build_package(args)
    except (ValueError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print('FAIL: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
