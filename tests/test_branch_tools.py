#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Offline publication boundaries; fixtures never contain executable firmware."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import package_source as p
spec = importlib.util.spec_from_file_location('branch_build', ROOT / 'build.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


def fixture(model='N'):
    revision, stock, image, updater = p.RELEASES[model]
    reverse_files = p.NS_REVERSE if model in ('N', 'S') else p.FO_REVERSE
    files = {name: b'fixture\n' for name in p.REQUIRED | reverse_files}
    frozen = {'test_%03d.py' % i: ('# fixture %s\n' % i).encode('ascii') for i in range(125)}
    files.update({'firmware/' + name: data for name, data in frozen.items()})
    profile = {'schema': p.PROFILE_FORMAT, 'model': model, 'brand': 'Test brand',
               'stock_revision': revision, 'branch': 'test-air2-m2', 'tag': 'test-air2-m2-20261016',
               'version': 'AIR2-P8-M2', 'name_slug': 'AirRemote_TTL_%s_AIR2_P8_M2' % model,
               'inner_exe_name': 'Air-Remote-TTL-%s-AIR2-P8-M2.exe' % model,
               'firmware_files': {name: p.sha(data) for name, data in frozen.items()},
               'expected': {'image_sha256': image, 'exe_sha256': updater}}
    files['release_profile.json'] = p.encoded(profile)
    files['model.json'] = p.encoded({'model': 'Air Remote TTL-' + model, 'version': revision,
                                   'source_sha256': stock})
    return files


def zip_fixture(files, prefix='AirRemote_TTL_N_AIR2_P8_M2_Source', extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in files.items():
            archive.writestr(prefix + '/' + name, data)
        archive.writestr(prefix + '/source_manifest.json', p.encoded(p.source_manifest(files)))
        if extra:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                for name, data in extra:
                    archive.writestr(name, data)
    return stream.getvalue()


class BranchToolsTests(unittest.TestCase):
    def test_fixed_identities(self):
        for model in ('N', 'S', 'F', 'O'):
            with self.subTest(model=model):
                files = fixture(model)
                profile, original = p.validate_files(files)
                profile['expected']['exe_sha256'] = '0' * 64
                with self.assertRaisesRegex(ValueError, 'Fixed M2 output'):
                    p.validate_profile(profile, original)

    def test_mismatched_original_model(self):
        files = fixture()
        profile, original = p.validate_files(files)
        original['model'] = 'Air Remote TTL-S'
        with self.assertRaisesRegex(ValueError, 'Original profile/model'):
            p.validate_profile(profile, original)

    def test_frozen_source_mutation_or_addition(self):
        for name in ('firmware/test_000.py', 'firmware/added.py'):
            with self.subTest(name=name):
                files = fixture()
                files[name] = b'# changed\n'
                with self.assertRaisesRegex(ValueError, 'Frozen firmware source'):
                    p.validate_files(files)

    def test_required_source(self):
        files = fixture()
        del files['windows/installer.nsi']
        with self.assertRaisesRegex(ValueError, 'Missing required'):
            p.validate_files(files)

    def test_archive_roundtrip_and_pin(self):
        files = fixture()
        data = zip_fixture(files)
        parsed, manifest = p.parse_archive(data, p.sha(data))
        self.assertEqual(parsed, files)
        self.assertEqual(manifest['format'], 'airremote-air2-branch-source-v1')
        with self.assertRaisesRegex(ValueError, 'archive fingerprint'):
            p.parse_archive(data, '0' * 64)

    def test_manifest_does_not_allow_changed_document(self):
        files = fixture()
        manifest = p.source_manifest(files)
        files['README.md'] += b'changed\n'
        with self.assertRaisesRegex(ValueError, 'manifest or file fingerprints'):
            p.verify_manifest(files, manifest)

    def test_unsafe_archive_path(self):
        for name in ('AirRemote_TTL_N_AIR2_P8_M2_Source/../leak.md',
                     'AirRemote_TTL_N_AIR2_P8_M2_Source/C:/leak.md'):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'Unsafe relative path'):
                    p.parse_archive(zip_fixture(fixture(), extra=[(name, b'bad')]))
        # ZipInfo normalizes native Windows separators on construction. Exercise
        # the raw-name gate directly instead of accidentally testing a good ZIP.
        with self.assertRaisesRegex(ValueError, 'Unsafe relative path'):
            p.safe_relative('AirRemote_TTL_N_AIR2_P8_M2_Source/a\\b.md')

    def test_duplicate_archive_entry(self):
        name = 'AirRemote_TTL_N_AIR2_P8_M2_Source/README.md'
        with self.assertRaisesRegex(ValueError, 'Duplicate source ZIP'):
            p.parse_archive(zip_fixture(fixture(), extra=[(name, b'bad')]))

    def test_wrong_archive_model_root(self):
        with self.assertRaisesRegex(ValueError, 'Wrong source ZIP root'):
            p.parse_archive(zip_fixture(fixture(), prefix='AirRemote_TTL_S_AIR2_P8_M2_Source'))

    def test_existing_output_and_source_output_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Output already exists'):
            b.checked_output(ROOT, ROOT)
        with self.assertRaisesRegex(ValueError, 'under build/ or dist/'):
            b.checked_output(ROOT / 'firmware' / 'new-output', ROOT)

    def test_wrong_original_is_read_only(self):
        retained = ROOT / 'build' / 'tests'
        retained.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='branch-tools-', dir=str(retained)))
        original = folder / 'fixture.bin'
        original.write_bytes(b'not an executable')
        profile = {'source_size': 17, 'source_sha256': '0' * 64,
                   'model': 'Air Remote TTL-N', 'version': 'C5'}
        with self.assertRaisesRegex(ValueError, 'Wrong original updater'):
            b.checked_original(original, profile)
        self.assertEqual(original.read_bytes(), b'not an executable')

    def test_duplicate_profile_json_key_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            p.parse_json(b'{"model":"N","model":"S"}')

    def test_archive_output_cannot_contaminate_source(self):
        for output in (ROOT, ROOT / 'tools' / 'output'):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, 'under build/, dist/ or artifacts/'):
                    p.package_output(ROOT, output)
        self.assertEqual(p.package_output(ROOT, ROOT / 'artifacts'), ROOT / 'artifacts')


if __name__ == '__main__':
    unittest.main(verbosity=2)
