#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Freeze and verify one model's corresponding source; no firmware execution."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'airremote-air2-branch-source-v1'
PROFILE_FORMAT = 'airremote-air2-release-profile-v1'
DATE = (2026, 10, 16, 0, 0, 0)
EXCLUDED = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'artifacts', 'outputs', '.tmp'}
SUFFIXES = {'.py', '.md', '.txt', '.json', '.c', '.h', '.nsi', '.bin', '.yml', '.yaml'}
REQUIRED = {'build.py', 'README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE.md',
            'NOTICE.zh-CN.md', 'DISCLAIMER.md', 'DISCLAIMER.zh-CN.md', 'CHANGELOG.md',
            'CHANGELOG.zh-CN.md', '.gitignore', '.gitattributes', 'model.json',
            'release_profile.json', 'reverse/README.md', 'reverse/README.zh-CN.md',
            'reverse/original_contract.json', 'reverse/provenance.json',
            'tools/package_source.py', 'tools/inspect_original.py',
            'windows/build_package.py', 'windows/installer.nsi',
            'windows/input_manifest.json'}
NS_REVERSE = {'reverse/original.pseudocode.c', 'reverse/source_map.json'}
FO_REVERSE = {'reverse/pseudocode/' + name + '.c' for name in
              ('hss_boundaries', 'keyboard_clock', 'nv_startup', 'radio', 'ui_abc')}
# Independent immutable release identities. The model selector is part of the
# reviewed branch profile; a caller cannot supply an alternative CLI target.
RELEASES = {
    'N': ('C5', '4fa0d7c1ae8201910e0586eef30feadb9230e3c30c7b67b8dc4c2d344dea5591',
          '01dc7913cb007a4d9cd7aafd295714bfba1f2b2f1d0dc261f70b647139b6966b',
          '0866e0186c3722a0c310bd73a206755b11c575f5765d924600d68c13958f1c17'),
    'S': ('A6', '707b65d9cb6ea6c320976e5a6244de05b1f0856ab9c7ddc5008fe739337b9737',
          'e159e3accf1271af66e52b11b626433d5cd7136c8b2717b44f441b4730bbf287',
          '5432bcbf1c136d940c717dd01fa9fa800f27961dbd78520b4da27303b31c0262'),
    'F': ('A5', '455b3f8eb74c2a598d5bd679d3450e9850860eae8de84362da71edb4896e4e6a',
          'edf60a81b787b0548f481133f899fc3f58b7f5a1ce4d5194cb90826600e6e1e5',
          'ac0fbd824a6fa23c754b352e7293caa2675500d6921188153c012272cdc0e3de'),
    'O': ('A4', '80ae4cac56c6bb7c363062d3ed7927373e4b7a907df8abbc2fed6731621a52b5',
          '67b3db05f412dfb33c1c7173693d4bf71b720a59265cd5b3feb2b7563a13ae95',
          'd07ee22f348e29e422e4af73a1c4427af3f80ce09633697c7073dd46b1820e93'),
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def parse_json(data):
    value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=unique_object)
    need(isinstance(value, dict), 'Expected a JSON object')
    return value


def safe_relative(name):
    need(isinstance(name, str) and name and '\\' not in name and ':' not in name,
         'Unsafe relative path')
    parts = PurePosixPath(name)
    need(not parts.is_absolute() and str(parts) == name and
         all(p not in ('', '.', '..') for p in name.split('/')) and
         not any(ord(c) < 32 for c in name), 'Unsafe relative path: ' + name)
    return parts


def validate_profile(profile, model):
    need(profile.get('schema') == PROFILE_FORMAT, 'Wrong release profile format')
    target = profile.get('model')
    need(target in RELEASES, 'Unsupported model')
    revision, original, image, updater = RELEASES[target]
    need(profile.get('version') == 'AIR2-P8-M2' and profile.get('stock_revision') == revision,
         'Wrong fixed release identity')
    need(model.get('model') == 'Air Remote TTL-' + target and model.get('version') == revision,
         'Original profile/model mismatch')
    need(model.get('source_sha256') == original, 'Original profile fingerprint differs')
    need(profile.get('expected') == {'image_sha256': image, 'exe_sha256': updater},
         'Fixed M2 output fingerprints differ')
    need(profile.get('inner_exe_name') == 'Air-Remote-TTL-%s-AIR2-P8-M2.exe' % target,
         'Wrong inner updater filename')
    need(profile.get('name_slug') == 'AirRemote_TTL_%s_AIR2_P8_M2' % target,
         'Wrong release source name')
    for key in ('branch', 'tag', 'brand'):
        need(isinstance(profile.get(key), str) and profile[key].strip(), 'Missing identity: ' + key)
    firmware_files = profile.get('firmware_files')
    need(isinstance(firmware_files, dict) and len(firmware_files) == 125,
         'Expected the complete 125-file frozen M2 source closure')
    for name, fingerprint in firmware_files.items():
        safe_relative(name)
        need(isinstance(fingerprint, str) and re.fullmatch('[0-9a-f]{64}', fingerprint),
             'Bad frozen source fingerprint: ' + name)
    return profile


def validate_files(files):
    need(REQUIRED.issubset(files), 'Missing required source files: ' + str(sorted(REQUIRED - files.keys())))
    profile = parse_json(files['release_profile.json'])
    model = parse_json(files['model.json'])
    validate_profile(profile, model)
    required_reverse = NS_REVERSE if profile['model'] in ('N', 'S') else FO_REVERSE
    need(required_reverse.issubset(files),
         'Missing model-specific reverse source: ' + str(sorted(required_reverse - files.keys())))
    actual_firmware = {name[len('firmware/'):]: sha(data) for name, data in files.items()
                       if name.startswith('firmware/')}
    need(actual_firmware == profile['firmware_files'], 'Frozen firmware source inventory/fingerprints differ')
    return profile, model


def inventory(root=ROOT):
    root = Path(root).resolve()
    files = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if EXCLUDED.intersection(relative.parts) or name == 'source_manifest.json':
            continue
        if relative.parts[0] == 'inputs' and path.name not in ('README.md', 'README.zh-CN.md'):
            continue
        need(not path.is_symlink(), 'Source tree contains a symbolic link: ' + name)
        if not path.is_file():
            continue
        need(path.suffix.lower() in SUFFIXES or path.name in ('LICENSE', '.gitignore', '.gitattributes'),
             'Unexpected source file type: ' + name)
        need(path.suffix.lower() != '.bin' or 'reference' in relative.parts,
             'Only generic reference parameters may be binary source: ' + name)
        data = path.read_bytes()
        need(len(data) < 16 * 1024 * 1024, 'Oversized source: ' + name)
        if path.suffix.lower() != '.bin':
            text = data.decode('utf-8-sig')
            for private in (str(root), str(Path.home()), str(root).replace('\\', '/')):
                need(private not in text, 'Local absolute path in source: ' + name)
        files[name] = data
    validate_files(files)
    return files


def source_manifest(files):
    profile, model = validate_files(files)
    return {'format': FORMAT, 'name': profile['version'], 'version': profile['version'],
            'model': profile['model'], 'branch': profile['branch'], 'release_tag': profile['tag'],
            'packaging_tag': parse_json(files['macos/model.json'])['packaging_tag'] if 'macos/model.json' in files else None,
            'release_date': profile.get('release_date', '2026-10-16'), 'developer': 'Caimankekw',
            'license': 'AGPL-3.0-only; authored material only; see NOTICE.md',
            'hardware_validated': False, 'original_updater_sha256': model['source_sha256'],
            'firmware_sha256': profile['expected']['image_sha256'],
            'updater_sha256': profile['expected']['exe_sha256'],
            'files': {name: {'size': len(data), 'sha256': sha(data)} for name, data in sorted(files.items())},
            'scope': 'Branch source and generic reference parameters; no vendor updater, device capture or build output.'}


def verify_manifest(files, manifest):
    expected = source_manifest(files)
    need(manifest == expected, 'Source manifest or file fingerprints differ')
    return manifest


def parse_archive(data, expected_sha=None):
    if expected_sha is not None:
        need(sha(data) == expected_sha, 'Source archive fingerprint differs')
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        need(1 < len(infos) < 1000, 'Source ZIP entry count outside bounds')
        need(sum(i.file_size for i in infos) < 64 * 1024 * 1024, 'Oversized source ZIP')
        need(archive.testzip() is None, 'Source ZIP CRC failed')
        prefixes = set()
        for info in infos:
            full = safe_relative(info.filename)
            need(not info.is_dir() and len(full.parts) > 1, 'Unexpected source ZIP entry')
            prefixes.add(full.parts[0])
            name = '/'.join(full.parts[1:])
            need(name not in files, 'Duplicate source ZIP entry')
            need(not (info.flag_bits & 1) and (info.external_attr >> 16) & 0o170000 != 0o120000,
                 'Encrypted or symbolic source entry')
            need(not EXCLUDED.intersection(full.parts[1:]), 'Generated/private source ZIP entry: ' + name)
            need(info.file_size < 16 * 1024 * 1024, 'Oversized source entry')
            need(Path(name).suffix.lower() in SUFFIXES or Path(name).name in ('LICENSE', '.gitignore', '.gitattributes'),
                 'Unexpected source ZIP file type: ' + name)
            need(Path(name).suffix.lower() != '.bin' or 'reference' in full.parts,
                 'Unexpected binary source entry: ' + name)
            files[name] = archive.read(info)
    need('source_manifest.json' in files, 'Source manifest missing')
    manifest = parse_json(files.pop('source_manifest.json'))
    profile, _ = validate_files(files)
    need(prefixes == {profile['name_slug'] + '_Source'}, 'Wrong source ZIP root')
    verify_manifest(files, manifest)
    return files, manifest


def verify(archive):
    archive = Path(archive)
    data = archive.read_bytes()
    files, manifest = parse_archive(data)
    return {'status': 'PASS', 'archive': archive.name, 'size': len(data), 'sha256': sha(data),
            'source_files': len(files), 'model': manifest['model'], 'release_tag': manifest['release_tag'],
            'frozen_firmware_files': 125, 'vendor_executable_included': False, 'device_accessed': False}


def verify_tree(root=ROOT):
    root = Path(root)
    files = inventory(root)
    manifest = parse_json((root / 'source_manifest.json').read_bytes())
    verify_manifest(files, manifest)
    return files, manifest


def package_output(root, output):
    root = Path(root).resolve()
    output = Path(output).absolute()
    for parent in (output,) + tuple(output.parents):
        need(not parent.is_symlink(), 'Source output contains a symbolic link')
    output = output.resolve()
    try:
        relative = output.relative_to(root)
    except ValueError:
        relative = None
    need(relative is None or (relative.parts and relative.parts[0] in ('build', 'dist', 'artifacts')),
         'A source archive output within this tree must be under build/, dist/ or artifacts/')
    return output


def package(root, output):
    root = Path(root).resolve()
    output = package_output(root, output)
    files = inventory(root)
    profile, _ = validate_files(files)
    manifest = source_manifest(files)
    encoded_manifest = encoded(manifest)
    manifest_path = root / 'source_manifest.json'
    previous = manifest_path.read_bytes() if manifest_path.exists() else None
    changed_manifest = previous is not None and previous != encoded_manifest
    archive = output / (profile['name_slug'] + '_Source.zip')
    report = output / 'source_package_verification.json'
    prior_manifest = output / 'source_manifest.previous.json'
    need(not archive.exists() and not report.exists(), 'Source output exists; select a new --out directory')
    need(not changed_manifest or not prior_manifest.exists(),
         'Prior manifest backup exists; select a new --out directory')
    output.mkdir(parents=True, exist_ok=True)
    if changed_manifest:
        prior_manifest.write_bytes(previous)
    if previous != encoded_manifest:
        manifest_path.write_bytes(encoded_manifest)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        all_files = dict(files)
        all_files['source_manifest.json'] = encoded_manifest
        for name, data in sorted(all_files.items()):
            entry = zipfile.ZipInfo(profile['name_slug'] + '_Source/' + name, DATE)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            zipped.writestr(entry, data)
    result = verify(archive)
    frozen, _ = parse_archive(archive.read_bytes())
    need(frozen == files, 'Source archive differs from live files')
    result['all_files_match_sources'] = True
    report.write_bytes(encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    result = verify(args.verify) if args.verify else package(ROOT, args.out)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
