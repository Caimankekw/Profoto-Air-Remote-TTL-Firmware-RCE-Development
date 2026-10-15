#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (c) 2026 Caimankekw
"""Olympus A4 native helper contract. Offline, stock-code adapters only.

No Canon HSS baseline, device access or flashable output is imported here.
All addresses are PIC18 byte addresses. The executable tests use original
helper bytes, not Python replacements for their arithmetic/queue behavior.
"""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
STOCK = HERE.parent / 'shared' / 'stock' / 'O'
IMAGE_SHA256 = '84645f098eeab93dd41d150015c7c642207037b7605b937b0a13388df1805976'
MASK_SHA256 = '81fe4da4f8a15728c97bc6de35fae71572d44f39a927dce22a9ca300b5d2558b'
BASE = 0x4000

ENTRY = {
    'bcd_unsigned': 0xA55C,
    'format_signed_tenths': 0x742E,
    'write_sign': 0x688E,
    'write_glyph': 0xA10E,
    'write_row_dashes': 0xA90E,
    'write_row_blank': 0xA91E,
    'clear_decimal': 0x94E6,
    'ring_initialize': 0x8FBA,
    'ring_put': 0x7112,
    'ring_get': 0x74AE,
    'radio_enqueue16': 0x9F1E,
    'radio_prefix': 0x82B0,
    'radio_admission': 0x919E,
    'radio_wire_size': 0x9F8A,
    'radio_type': 0xABD8,
    'manual_delta': 0x86D6,
    'mode_toggle': 0x6A62,
}
RAM = {
    'config': 0x199, 'mode': 0x199,
    'ttl_fec': (0x19D, 0x19E, 0x19F),
    'relative': (0x036, 0x037, 0x038),
    'head_mask': 0x02C, 'model_mask': 0x03F,
    'selected_group': 0x060,
    'ui_state': 0x082,
    'native_radio_block': 0x02A,
    'lcd': (0x08A, 0x095), 'rows': (0x08B, 0x08D, 0x08F),
    'ring_descriptor': 0x095, 'ring_buffer': 0x300, 'ring_length': 100,
    'packet_buffer': 0x0C1,
    'keys': {'mode':0x100, 'A':0x10C, 'B':0x110, 'C':0x114,
             'model':0x118, 'head':0x11C, 'plus':0x120, 'minus':0x124},
}
GLYPH_DIGITS = bytes.fromhex('6f 60 5e 7c 71 3d 3f 64 7f 7d')
SIGN = {0x8B:(0x8A, 0x80, 0x40),
        0x8D:(0x91, 0x02, 0x01), 0x8F:(0x91, 0x08, 0x04)}
NATIVE_SETTINGS = (0x1F800, 0x1FC00)


def stock():
    image = (STOCK / 'original.base4000.partial.bin').read_bytes()
    mask = (STOCK / 'original.known_mask.bin').read_bytes()
    if hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise ValueError('Olympus A4 stock changed')
    if hashlib.sha256(mask).hexdigest() != MASK_SHA256:
        raise ValueError('Olympus A4 known mask changed')
    return image, mask


def initialize_radio_ring(cpu):
    """Call the real initializer with the original descriptor and allocation."""
    cpu.m[0x1E:0x23] = bytes((0x95, 0, 0, 3, 100))
    cpu.run(ENTRY['ring_initialize'], max_steps=2000)


def set_formatter_arguments(cpu, row, value):
    if row not in RAM['rows'] or not -99 <= value <= 100:
        raise ValueError('unsupported native signed-tenths input')
    cpu.m[0xFE0] = 0
    cpu.m[0xB7:0xBA] = bytes((0x8A, row, value & 255))


def clear_sign_arguments(cpu, row):
    if row not in RAM['rows']:
        raise ValueError('unknown LCD row')
    cpu.m[0x1E:0x21] = bytes((0x8A, row, 2))


def cmd11_body(targets, head, model):
    """Protocol body only; not an assertion of receiver/hardware acceptance.

    Targets are already encoded Air absolute-power bytes, not panel tenths.
    Encoding, mode policy and retry are the shared core's responsibility.
    """
    if len(targets) != 6 or any(not 0 <= x <= 255 for x in targets):
        raise ValueError('six encoded target bytes required')
    if not 0 <= head <= 63 or not 0 <= model <= 63:
        raise ValueError('six-group switch masks required')
    return bytes((0x27,0xFF,0xFF,0xFF,1,0x11,*targets,head,model,0,0))
