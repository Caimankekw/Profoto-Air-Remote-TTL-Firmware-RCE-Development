# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Offline profile and executable boundary tests; no compilers, installers or USB."""
import copy
import json
import struct
import unittest
import build_package as p


def profile_fixture(model='N'):
    brand, revision = p.MODELS[model]
    return ({'schema': 'airremote-air2-release-profile-v1', 'model': model, 'brand': brand,
             'stock_revision': revision, 'version': 'AIR2-P8-M2', 'product_version': '8.0.2.0',
             'name_slug': 'AirRemote_TTL_' + model + '_AIR2_P8_M2',
             'inner_exe_name': 'Air-Remote-TTL-' + model + '-AIR2-P8-M2.exe',
             'branch': brand.lower() + '-air2-m2', 'tag': brand.lower() + '-air2-m2-20261016',
             'expected': {'image_sha256': '1' * 64, 'exe_sha256': '2' * 64}},
            {'model': 'Air Remote TTL-' + model, 'version': revision, 'source_sha256': '3' * 64})


def version_node(key, value=b'', children=(), kind=1):
    result = bytearray(struct.pack('<HHH', 0, len(value) // (2 if kind else 1), kind))
    result += (key + '\0').encode('utf-16le')
    result += bytes((-len(result)) % 4)
    result += value
    for child in children:
        result += bytes((-len(result)) % 4)
        result += child
    struct.pack_into('<H', result, 0, len(result))
    return bytes(result)


def pe_fixture(company='Caimankekw', elevation='asInvoker', model='N'):
    strings = [version_node(k, (v + '\0').encode('utf-16le')) for k, v in (
        ('CompanyName', company), ('ProductName', 'Air Remote TTL-' + model + ' AIR2-P8-M2 Custom Updater'))]
    version = version_node('VS_VERSION_INFO', bytes(52), [
        version_node('StringFileInfo', children=[version_node('040904b0', children=strings)])], kind=0)
    manifest = ('<assembly><trustInfo><security><requestedPrivileges><requestedExecutionLevel level="' +
                elevation + '" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>').encode()
    output = bytearray(0xA00)
    output[:2] = b'MZ'
    struct.pack_into('<I', output, 0x3C, 0x80)
    output[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', output, 0x84, 0x14C, 1, 0, 0, 0, 224, 0)
    struct.pack_into('<H', output, 0x98, 0x10B)
    struct.pack_into('<II', output, 0x98 + 96 + 16, 0x1000, 0x800)
    struct.pack_into('<8sIIIIIIHHI', output, 0x178, b'.rsrc\0\0\0', 0x800, 0x1000, 0x800, 0x200, 0, 0, 0, 0, 0)
    base = 0x200
    struct.pack_into('<HH', output, base + 12, 0, 2)
    struct.pack_into('<IIII', output, base + 16, 16, 0x80000020, 24, 0x80000038)
    for offset, next_offset in ((0x20, 0x50), (0x38, 0x68)):
        struct.pack_into('<HHII', output, base + offset + 12, 0, 1, 1, 0x80000000 | next_offset)
    for offset, leaf in ((0x50, 0x80), (0x68, 0x90)):
        struct.pack_into('<HHII', output, base + offset + 12, 0, 1, 1033, leaf)
    vpos = 0xA0
    mpos = (vpos + len(version) + 3) & ~3
    struct.pack_into('<IIII', output, base + 0x80, 0x1000 + vpos, len(version), 0, 0)
    struct.pack_into('<IIII', output, base + 0x90, 0x1000 + mpos, len(manifest), 0, 0)
    output[base + vpos:base + vpos + len(version)] = version
    output[base + mpos:base + mpos + len(manifest)] = manifest
    return bytes(output)


class PackageBoundaries(unittest.TestCase):
    def test_four_profiles_and_identity(self):
        for model in p.MODELS:
            profile, stock = profile_fixture(model)
            self.assertEqual(p.validate_profile(profile, stock), profile)
            self.assertTrue(p.verify_installer_pe(pe_fixture(model=model), profile)['as_invoker'])

    def test_swapped_original_model_rejected(self):
        for model in p.MODELS:
            profile, stock = profile_fixture(model)
            stock['model'] = 'Air Remote TTL-C'
            with self.assertRaises(ValueError):
                p.validate_profile(profile, stock)

    def test_profile_mismatch_rejected(self):
        for key, value in [('model', 'C'), ('brand', 'Canon'), ('stock_revision', 'C11'),
                           ('version', 'AIR2-P8-M1'), ('product_version', '8.0.1.0'),
                           ('inner_exe_name', 'other.exe'), ('name_slug', 'wrong'),
                           ('branch', '../../wrong'), ('tag', 'a" /Dwrong'), ('release_date', 'bad')]:
            with self.subTest(key=key):
                profile, stock = profile_fixture()
                profile[key] = value
                with self.assertRaises(ValueError):
                    p.validate_profile(profile, stock)

    def test_profile_hash_rejected(self):
        profile, stock = profile_fixture()
        profile['expected']['exe_sha256'] = 'invalid'
        with self.assertRaises(ValueError):
            p.validate_profile(profile, stock)

    def test_wrong_updater_hash_rejected(self):
        with self.assertRaises(ValueError):
            p.pinned(b'wrong updater', '0' * 64, 'test')

    def test_vendor_notice_pin(self):
        pins = json.loads((p.HERE / 'input_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(pins['vendor_notice_sha256'],
                         '7d41f0e5609df0750aa07c9a1fb3c9cd7d1ce917d7b51c498db212c25854e1ce')
        self.assertEqual(pins['nsis']['version'], '3.13')

    def test_templates_for_four_models(self):
        for model in p.MODELS:
            profile, stock = profile_fixture(model)
            for name in ('README.md', 'README.zh-CN.md'):
                blob = p.render_template((p.HERE / 'templates' / name).read_bytes(), profile, stock)
                self.assertIn(profile['expected']['exe_sha256'].encode(), blob)
                self.assertIn(profile['inner_exe_name'].encode(), blob)
                self.assertNotIn(b'@MODEL@', blob)
                self.assertNotIn(b'AIR2-P8-FIX1', blob)

    def test_unknown_template_field_rejected(self):
        profile, stock = profile_fixture()
        with self.assertRaises(ValueError):
            p.render_template(b'@UNKNOWN@', profile, stock)

    def test_wrong_company_or_product_rejected(self):
        profile, _ = profile_fixture()
        for data in (pe_fixture(company='SomeoneElse'), pe_fixture(model='S')):
            with self.assertRaises(ValueError):
                p.verify_installer_pe(data, profile)

    def test_elevated_wrapper_rejected(self):
        profile, _ = profile_fixture()
        with self.assertRaises(ValueError):
            p.verify_installer_pe(pe_fixture(elevation='requireAdministrator'), profile)

    def test_malformed_pe_rejected(self):
        profile, _ = profile_fixture()
        for data in (b'', b'MZ', bytes(0x100), pe_fixture()[:0x250]):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                p.verify_installer_pe(data, profile)

    def test_version_bounds_rejected(self):
        value = bytearray(version_node('VS_VERSION_INFO', bytes(52), kind=0))
        struct.pack_into('<H', value, 0, len(value) + 10)
        with self.assertRaises(ValueError):
            p.version_strings(value)

    def test_current_installer_controls(self):
        text = (p.HERE / 'installer.nsi').read_text(encoding='utf-8')
        self.assertIn('!define MUI_FINISHPAGE_RUN_NOTCHECKED', text)
        self.assertEqual(text.count('!insertmacro MUI_PAGE_LICENSE'), 2)
        self.assertIn('RequestExecutionLevel user', text)
        self.assertIn('SetOverwrite off', text)
        self.assertNotIn('WriteUninstaller', text)
        self.assertNotIn('Delete ', text)
        self.assertNotIn('Canon', text)
        self.assertNotIn('FIX1', text)
        self.assertEqual(text.count("  Exec '"), 1)
        self.assertIn('VIProductVersion "8.0.2.0"', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
