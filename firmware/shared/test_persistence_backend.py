#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Actual emitted PIC18 replay with an explicit 47J13/J53 flash boundary.

Only electrical flash effects are supplied by the harness. Record scanning,
CRC, sequencing, comparison, page selection and unlock instructions are real.
"""
import unittest

import persistence_backend as backend
from pic18_vm import CPU
from state_model import NvRecord, crc_ccitt_false


STATE = 0x680
ORIGIN = 0xB000
READ_INPUTS = 0xAF00
PROOF = dict(hardware_proven=True, ram_proven=True, pages_proven=True,
             isr_context_proven=True, flash_bytes=0x20000, erase_bytes=1024,
             write_bytes=2, eecon1=0xFA6, eecon2=0xFA7, wprog_bit=5)


def record(sequence=0, target=50, tag='F', mode=1, last=2, page=1):
    return NvRecord(tag, mode, last, (target, 21, 32, 43, 54, 65),
                    0x15, 0x2A, page, sequence).encode()


def altered(data, offset, value, repair_crc=True):
    data = bytearray(data)
    data[offset] = value
    if repair_crc:
        data[28:30] = crc_ccitt_false(data[:28]).to_bytes(2, 'little')
    return bytes(data)


class PowerLoss(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class FlashController:
    """Explicit device boundary, never a replacement for an emitted routine."""
    def __init__(self, cpu, *, cut_after=None, fail_word=None, partial_word=False,
                 fail_erase=False, busy_after=None, cut_erase=False):
        self.cpu = cpu
        self.cut_after, self.fail_word = cut_after, fail_word
        self.partial_word, self.fail_erase = partial_word, fail_erase
        self.busy_after = busy_after
        self.cut_erase = cut_erase
        self.unlock = []
        self.operations = []
        self.words = 0
        cpu.write_hooks[0xFA6] = self.control
        cpu.write_hooks[0xFA7] = self.key

    def key(self, cpu, value):
        cpu.m[0xFA7] = value
        self.unlock.append(value)

    def control(self, cpu, value):
        cpu.m[0xFA6] = value
        if not value & 2:
            return
        require(self.unlock == [0x55, 0xAA], self.unlock)
        self.unlock.clear()
        require(value & 4, 'WREN must be enabled')
        require(not cpu.m[0xFF2] & 0xC0, 'unlock must mask both interrupt enables')
        pointer = cpu.tblptr()
        if value & 0x10:
            require(not value & 0x20, 'erase must clear WPROG')
            require(pointer in backend.PAGES, 'erase must target owned page start')
            self.operations.append(('erase', pointer))
            cpu.flash[pointer:pointer + 1024] = b'\xff' * 1024
            if self.fail_erase:
                cpu.flash[pointer + 1023] = 0
            if self.cut_erase:
                raise PowerLoss()
        else:
            require(value & 0x20, 'word programming must select WPROG')
            start = pointer & ~1
            require(pointer == start + 1, 'second TBLWT must not postincrement')
            require(0xF800 <= start <= 0xFFFE, 'word must target owned pages')
            require(start in cpu.latches and start + 1 in cpu.latches, 'both latches required')
            if self.cut_after == self.words:
                if self.partial_word:
                    cpu.flash[start] &= cpu.latches[start]
                raise PowerLoss()
            self.words += 1
            self.operations.append(('word', start))
            for index in range(2):
                if self.fail_word != self.words or (self.partial_word and index == 0):
                    cpu.flash[start + index] &= cpu.latches[start + index]
            if self.fail_word == self.words and not self.partial_word:
                cpu.m[0xFA6] |= 8
            if self.busy_after == self.words:
                cpu.m[0x20] = 0x80
        cpu.latches.clear()
        cpu.m[0xFA6] &= ~2
        # A peripheral pending flag arriving during masked time must survive.
        cpu.m[0xFF2] |= 1


def machine(flash=None, tag='F', irq=0xC4, enabled=True, **faults):
    proof = dict(PROOF)
    if not enabled:
        proof['hardware_proven'] = False
    result = backend.construct(code_origin=ORIGIN, state_base=STATE,
                               profile={'model_tag': tag}, backend=proof,
                               imports={'read_inputs': READ_INPUTS})
    body = result['sections'][0]['data']
    image = bytearray(b'\xff' * (ORIGIN - READ_INPUTS + len(body)))
    # An explicit miniature native sampler: input20 -> snapshot77, clobber FSR2
    # and BSR as permitted by the native ABI, return W1.
    sampler = backend.words(0xC020, 0xF000 | STATE + 0x77,
                                      0xEE24, 0xF056, 0x0103, 0x0C01)
    image[:len(sampler)] = sampler
    image[ORIGIN - READ_INPUTS:] = body
    if flash is None:
        flash = bytearray(b'\xff' * 0x20000)
    values = {0xFA6: 0, 0xFA7: 0, 0xFF2: irq, 0x20: 0x84}
    cpu = CPU(image, values=values, base=READ_INPUTS, flash=flash,
              allowed_sfr=(0xFA6, 0xFA7, 0xFF2), max_steps=2000000)
    controller = FlashController(cpu, **faults)
    return cpu, result, controller


def invoke(cpu, result, name, candidate=None):
    if candidate is not None:
        cpu.m[STATE + 0x40:STATE + 0x60] = candidate
    cpu.run(result['exports'][name])
    return cpu.w


def loaded(flash, tag='F'):
    cpu, result, _ = machine(flash, tag)
    status = invoke(cpu, result, 'nv_load')
    return bytes(cpu.m[STATE + 0x40:STATE + 0x60]) if status else None


class PersistenceTests(unittest.TestCase):
    def test_construct_proof_and_range_gates(self):
        cpu, result, controller = machine(enabled=False)
        self.assertFalse(result['metadata']['nv_enabled'])
        self.assertEqual(invoke(cpu, result, 'nv_commit', record()), 0)
        self.assertEqual(controller.operations, [])
        with self.assertRaises(ValueError):
            backend.construct(code_origin=0xF7FE, profile={'model_tag': 'F'}, backend=PROOF)
        with self.assertRaises(ValueError):
            backend.construct(b'\xff' * 100, code_origin=ORIGIN,
                              profile={'model_tag': 'F'}, backend=PROOF)
        first = backend.construct(code_origin=ORIGIN, profile={'model_tag': 'F'}, backend=PROOF)
        second = machine()[1]
        self.assertEqual(first['unresolved_imports'], ['read_inputs'])
        self.assertEqual(first['exports'], second['exports'])
        self.assertEqual(len(first['sections'][0]['data']), len(second['sections'][0]['data']))

    def test_empty_and_commit_exact_round_trip_all_models(self):
        for tag in 'FNOS':
            with self.subTest(tag=tag):
                cpu, result, controller = machine(tag=tag)
                self.assertEqual(invoke(cpu, result, 'nv_load'), 0)
                self.assertEqual(invoke(cpu, result, 'nv_commit', record(500, tag=tag)), 1)
                actual = loaded(cpu.flash, tag)
                self.assertEqual(actual, record(0, tag=tag))
                self.assertEqual(controller.operations[-1], ('word', 0xF81E))
                self.assertEqual(len(controller.operations), 16)

    def test_compare_write_uses_payload_and_returns_durable_sequence(self):
        cpu, result, controller = machine()
        self.assertEqual(invoke(cpu, result, 'nv_commit', record()), 1)
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(4321)), 1)
        self.assertEqual(controller.words, 16)
        self.assertEqual(bytes(cpu.m[STATE + 0x40:STATE + 0x60]), record())
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(4321, target=51)), 1)
        self.assertEqual(loaded(cpu.flash), record(1, target=51))

    def test_all_modes_remembered_subtypes_and_pages_round_trip(self):
        for mode, last in ((0, 1), (0, 2), (1, 1), (1, 2)):
            for page in (0, 1):
                with self.subTest(mode=mode, last=last, page=page):
                    candidate = record(mode=mode, last=last, page=page)
                    cpu, result, _ = machine()
                    self.assertEqual(invoke(cpu, result, 'nv_commit', candidate), 1)
                    self.assertEqual(loaded(cpu.flash), candidate)

    def test_crc_torn_and_illegal_payloads_rejected_by_machine(self):
        cases = [altered(record(8), 28, 0, False),
                 altered(record(8), 31, 0xFF, False)]
        for offset, value in ((2, 4), (3, 3), (3, 1), (6, 0), (11, 101),
                              (12, 0x40), (13, 0x80), (14, 2), (15, 0),
                              (15, 3), (16, ord('N')), (17, 1), (27, 1)):
            cases.append(altered(record(8), offset, value))
        for bad in cases:
            with self.subTest(bad=bad.hex()):
                flash = bytearray(b'\xff' * 0x20000)
                flash[0xF800:0xF820] = record(7)
                flash[0xF820:0xF840] = bad
                self.assertEqual(loaded(flash), record(7))
                cpu, result, controller = machine(flash)
                self.assertEqual(invoke(cpu, result, 'nv_commit', bad), 0)
                self.assertEqual(controller.operations, [])

    def test_serial_wrap_and_half_range(self):
        flash = bytearray(b'\xff' * 0x20000)
        for i, sequence in enumerate((65534, 65535, 0, 1, 0x8001)):
            flash[0xF800 + 32 * i:0xF820 + 32 * i] = record(sequence, target=40 + i)
        self.assertEqual(loaded(flash), record(1, target=43))
        cpu, result, _ = machine(flash)
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(target=52)), 1)
        self.assertEqual(loaded(cpu.flash), record(2, target=52))

    def full_page(self, flash=None, page=0xF800, initial=0):
        flash = bytearray(b'\xff' * 0x20000) if flash is None else bytearray(flash)
        for i in range(32):
            flash[page + 32 * i:page + 32 * i + 32] = record(initial + i)
        return flash

    def test_rollover_erases_other_page_and_keeps_original_journal(self):
        flash = self.full_page()
        flash[0xFC00:0x10000] = b'\0' * 1024
        flash[0x1F800:0x1FC00] = bytes(range(256)) * 4
        cpu, result, controller = machine(flash)
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(target=61)), 1)
        self.assertEqual(controller.operations[0], ('erase', 0xFC00))
        self.assertEqual(loaded(cpu.flash), record(32, target=61))
        self.assertEqual(cpu.flash[0xF800:0xFC00], flash[0xF800:0xFC00])
        self.assertEqual(cpu.flash[0x1F800:0x1FC00], flash[0x1F800:0x1FC00])
        flash = self.full_page(cpu.flash, 0xFC00, 32)
        cpu, result, controller = machine(flash)
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(target=62)), 1)
        self.assertEqual(controller.operations[0], ('erase', 0xF800))
        self.assertEqual(loaded(cpu.flash), record(64, target=62))

    def test_torn_word_at_every_boundary_retains_old_record(self):
        for rollover in (False, True):
            for cut in range(16):
                for partial in (False, True):
                    with self.subTest(rollover=rollover, cut=cut, partial=partial):
                        flash = self.full_page() if rollover else bytearray(b'\xff' * 0x20000)
                        if not rollover:
                            flash[0xF800:0xF820] = record(31)
                        cpu, result, _ = machine(flash, cut_after=cut, partial_word=partial)
                        with self.assertRaises(PowerLoss):
                            invoke(cpu, result, 'nv_commit', record(target=71))
                        self.assertEqual(loaded(cpu.flash), record(31))

    def test_program_and_full_erase_readback(self):
        for faults in ({'fail_word': 5}, {'fail_word': 5, 'partial_word': True},
                       {'fail_erase': True}):
            with self.subTest(faults=faults):
                flash = self.full_page()
                flash[0xFC00:0x10000] = b'\0' * 1024
                cpu, result, controller = machine(flash, **faults)
                self.assertEqual(invoke(cpu, result, 'nv_commit', record(target=72)), 2)
                self.assertEqual(loaded(cpu.flash), record(31))
                if faults.get('fail_erase'):
                    self.assertEqual(controller.words, 0)

    def test_reset_after_erase_preserves_old_page(self):
        flash = self.full_page()
        flash[0xFC00:0x10000] = b'\0' * 1024
        cpu, result, controller = machine(flash, cut_erase=True)
        with self.assertRaises(PowerLoss):
            invoke(cpu, result, 'nv_commit', record(target=74))
        self.assertEqual(controller.words, 0)
        self.assertEqual(loaded(cpu.flash), record(31))

    def test_fresh_busy_gate_before_each_write(self):
        cpu, result, controller = machine(busy_after=1)
        cpu.flash[0xF800:0xF820] = record(31)
        self.assertEqual(invoke(cpu, result, 'nv_commit', record(target=73)), 0)
        self.assertEqual(controller.words, 1)
        self.assertEqual(loaded(cpu.flash), record(31))
        for flags in (0, 4, 0x80):
            cpu, result, controller = machine()
            cpu.m[0x20] = flags
            self.assertEqual(invoke(cpu, result, 'nv_commit', record()), 0)
            self.assertEqual(controller.operations, [])

    def test_architectural_context_canonical_state_and_irq_flags_preserved(self):
        for irq in (0x04, 0x44, 0x84, 0xC4):
            cpu, result, _ = machine(irq=irq)
            registers = result['metadata']['preserved_registers']
            for i, address in enumerate(registers):
                cpu.m[address] = (i + 3) & (15 if address in (0xFE0, 0xFEA, 0xFE2, 0xFDA) else 255)
            expected = {address: cpu.m[address] for address in registers}
            canonical = bytes((i * 7) & 255 for i in range(64))
            cpu.m[STATE:STATE + 64] = canonical
            cpu.m[0xFA6] = 8  # Preserve pre-existing WRERR on return.
            self.assertEqual(invoke(cpu, result, 'nv_commit', record()), 1)
            self.assertEqual({address: cpu.m[address] for address in registers}, expected)
            self.assertEqual(cpu.m[STATE:STATE + 64], canonical)
            self.assertEqual(cpu.m[0xFF2], irq | 1)
            self.assertEqual(cpu.m[0xFA6], 8)


if __name__ == '__main__':
    unittest.main()
