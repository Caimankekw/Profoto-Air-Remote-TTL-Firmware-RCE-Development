# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""In-memory boundary tests. Synthetic patches are never saved as firmware."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from repack_variants import Variant, BuildError, BASE, check_instruction_sequence


class RepackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.variants = {model: Variant(model) for model in 'NSFO'}

    def synthetic_plan(self, variant):
        # Select a real CALL only to exercise container editing. This does not
        # assert that a UI hook is appropriate at this address.
        hook = next(address for address in range(0x6000, 0x7000, 2)
                    if int.from_bytes(variant.plain[address - BASE:address - BASE + 2], 'little') & 0xFE00 == 0xEC00)
        return {
            'schema_version': 1, 'model': variant.model,
            'stock_sha256': variant.profile['source_sha256'],
            'hooks': [{'address': hook, 'expected_hex': variant.plain[hook - BASE:hook - BASE + 4].hex(),
                       'replacement_hex': '00000000', 'role': 'IN-MEMORY SYNTHETIC TEST ONLY'}],
            'sections': [{'address': 0xC000, 'data_hex': '00001200', 'role': 'IN-MEMORY SYNTHETIC TEST ONLY'}],
            'protected_ranges': [], 'validation': {},
        }

    def test_four_stock_containers_roundtrip(self):
        for model, variant in self.variants.items():
            with self.subTest(model=model):
                exe, hex_text, plain, report = variant.build(self.synthetic_plan(variant), require_complete=False)
                self.assertEqual(len(exe), len(variant.outer))
                self.assertEqual(exe[:variant.start], variant.outer[:variant.start])
                self.assertEqual(exe[variant.end:], variant.outer[variant.end:])
                self.assertEqual(plain[:0x100], variant.plain[:0x100])
                self.assertEqual(plain[0xF800 - BASE:], variant.plain[0xF800 - BASE:])
                self.assertTrue(report['full_codec_readback_exact'])
                self.assertFalse(report['device_boot_verified'])
                self.assertFalse(report['complete_offline_gate_required'])

    def test_incomplete_verification_refused(self):
        for variant in self.variants.values():
            with self.assertRaisesRegex(BuildError, 'Required verification'):
                variant.build(self.synthetic_plan(variant))

    def test_cross_model_plan_refused(self):
        plan = self.synthetic_plan(self.variants['N'])
        with self.assertRaisesRegex(BuildError, 'another model'):
            self.variants['S'].build(plan, require_complete=False)

    def test_preimage_mismatch_refused(self):
        variant = self.variants['F']
        plan = self.synthetic_plan(variant)
        plan['hooks'][0]['expected_hex'] = '00000000'
        with self.assertRaisesRegex(BuildError, 'preimage mismatch'):
            variant.build(plan, require_complete=False)

    def test_protected_native_range_refused(self):
        variant = self.variants['O']
        plan = self.synthetic_plan(variant)
        address = plan['hooks'][0]['address']
        plan['protected_ranges'] = [{'start': address, 'end': address + 4, 'label': 'HSS'}]
        with self.assertRaisesRegex(BuildError, 'intersects HSS'):
            variant.build(plan, require_complete=False)

    def test_overlap_refused(self):
        variant = self.variants['N']
        plan = self.synthetic_plan(variant)
        plan['sections'].append(copy.deepcopy(plan['sections'][0]))
        with self.assertRaisesRegex(BuildError, 'Overlapping'):
            variant.build(plan, require_complete=False)

    def test_nonempty_rom_refused(self):
        variant = self.variants['S']
        plan = self.synthetic_plan(variant)
        plan['sections'][0]['address'] = 0x8000
        with self.assertRaisesRegex(BuildError, 'overlaps original'):
            variant.build(plan, require_complete=False)

    def test_reserved_nvm_refused(self):
        variant = self.variants['F']
        plan = self.synthetic_plan(variant)
        plan['sections'][0]['address'] = 0xF800
        with self.assertRaisesRegex(BuildError, 'permitted application'):
            variant.build(plan, require_complete=False)

    def test_odd_instruction_refused(self):
        with self.assertRaisesRegex(BuildError, 'odd instruction'):
            check_instruction_sequence(b'\x00', 'test')

    def test_split_doubleword_refused(self):
        for opcode in (0xC123, 0xEC12, 0xED12, 0xEF12, 0xEE12):
            with self.subTest(opcode=hex(opcode)):
                with self.assertRaisesRegex(BuildError, 'split instruction'):
                    check_instruction_sequence(opcode.to_bytes(2, 'little'), 'test')

    def test_continuation_start_refused(self):
        with self.assertRaisesRegex(BuildError, 'continuation'):
            check_instruction_sequence(bytes.fromhex('12f0'), 'test')

    def test_invalid_doubleword_refused(self):
        with self.assertRaisesRegex(BuildError, 'invalid continuation'):
            check_instruction_sequence(bytes.fromhex('12ec0000'), 'test')


if __name__ == '__main__':
    unittest.main(verbosity=2)
