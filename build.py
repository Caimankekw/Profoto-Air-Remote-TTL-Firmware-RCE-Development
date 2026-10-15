#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Rebuild this branch's frozen AIR2-P8-M2 target offline from its stock updater.

Only reads the supplied vendor EXE as data. It never runs an updater, installs
drivers, accesses USB or flashes a device. Work directories are retained.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
import package_source as source


def checked_original(path, model):
    path = Path(path)
    source.need(path.is_file() and not path.is_symlink(), 'Original input must be a regular file')
    data = path.read_bytes()
    source.need(len(data) == model['source_size'] and source.sha(data) == model['source_sha256'],
                'Wrong original updater: this branch requires exactly ' + model['model'] + ' ' + model['version'])
    return data


def checked_output(output, root=ROOT):
    output = Path(output).absolute()
    for parent in (output,) + tuple(output.parents):
        source.need(not parent.is_symlink(), 'Output path contains a symbolic link')
    output = output.resolve()
    source.need(not output.exists(), 'Output already exists; choose a new --output directory')
    root = Path(root).resolve()
    try:
        relative = output.relative_to(root)
    except ValueError:
        relative = None
    source.need(relative is None or relative.parts[0] in ('build', 'dist'),
                'An output within the source tree must be under build/ or dist/')
    return output


def run_python(script, arguments, work, log):
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    command = [sys.executable, '-I', '-X', 'utf8', '-B', str(script)] + [str(a) for a in arguments]
    result = subprocess.run(command, cwd=str(work), env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log.write_bytes(result.stdout)
    source.need(result.returncode == 0, 'Offline subprocess failed; retained log: ' + str(log))


def build(original, output, root=ROOT):
    root = Path(root).resolve()
    files, manifest = source.verify_tree(root)
    profile = source.parse_json(files['release_profile.json'])
    model = source.parse_json(files['model.json'])
    original_data = checked_original(original, model)
    output = checked_output(output, root)
    target = profile['model']
    relative_input = source.safe_relative(model['source'])
    expected_path = ('air_remote_ttl/air-remote-ttl-%s-firmware-%s-win/'
                     'Air-Remote-TTL-%s-Firmware-%s.exe') % (
                         target.lower(), profile['stock_revision'].lower(), target, profile['stock_revision'])
    source.need(relative_input.as_posix() == expected_path, 'Unexpected original input layout')
    output.mkdir(parents=True)
    scratch = output / 'scratch' / 'firmware'
    scratch.mkdir(parents=True)
    for name in sorted(profile['firmware_files']):
        destination = scratch / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files['firmware/' + name])
    staged_original = scratch / 'inputs' / expected_path
    staged_original.parent.mkdir(parents=True)
    staged_original.write_bytes(original_data)
    artifacts = output / 'artifacts'
    run_python(scratch / 'shared' / 'inspect_variants.py',
               ['--firmware-root', scratch / 'inputs' / 'air_remote_ttl', '--model', target],
               scratch, output / 'inspect.log')
    run_python(scratch / 'shared' / 'build_variants.py',
               ['--model', target, '--profile', scratch / target / 'port_profile.json',
                '--source', staged_original, '--output', artifacts],
               scratch, output / 'build.log')
    updater = artifacts / profile['inner_exe_name']
    image = artifacts / (profile['inner_exe_name'][:-4] + '.partial.bin')
    hex_file = artifacts / (profile['inner_exe_name'][:-4] + '.hex')
    source.need(source.sha(updater.read_bytes()) == profile['expected']['exe_sha256'],
                'Rebuilt updater differs from frozen M2')
    source.need(source.sha(image.read_bytes()) == profile['expected']['image_sha256'],
                'Rebuilt image differs from frozen M2')
    integration = source.parse_json((artifacts / 'final_image_verification.json').read_bytes())
    replay = integration['integration']
    source.need(replay.get('full_integration_pass') is True and not replay.get('coverage_pending'),
                'Linked replay did not close its declared checks')
    # Recheck the actual input and published source after the subprocesses.
    source.need(Path(original).read_bytes() == original_data, 'Original updater changed during build')
    source.need(source.verify_tree(root)[0] == files, 'Branch source changed during build')
    result = {'format': 'airremote-air2-branch-rebuild-v1', 'status': 'PASS_OFFLINE_REBUILD',
              'model': target, 'branch': profile['branch'], 'release_tag': profile['tag'],
              'release': profile['version'],
              'source_manifest_sha256': source.sha((root / 'source_manifest.json').read_bytes()),
              'original_updater_sha256': model['source_sha256'],
              'artifacts': {path.name: {'size': path.stat().st_size, 'sha256': source.sha(path.read_bytes())}
                            for path in (updater, image, hex_file)},
              'frozen_firmware_files_verified': len(profile['firmware_files']),
              'linked_replay_status': replay['status'], 'full_integration_pass': True,
              'device_accessed': False, 'updater_executed': False, 'hardware_validated': False,
              'scope': 'Exact frozen M2 image/updater reproduction and bounded linked replay; not hardware qualification.'}
    (output / 'build_verification.json').write_bytes(source.encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True,
                        help='The exact original updater for this branch; read only as data')
    parser.add_argument('--output', type=Path, required=True, help='A new directory; scratch and logs are retained')
    args = parser.parse_args()
    print(json.dumps(build(args.original, args.output), indent=2))


if __name__ == '__main__':
    main()
