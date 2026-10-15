#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Caimankekw
"""Read pinned stock updater data for the four non-Canon AIR2 ports.

This tool never executes an updater or accesses USB. Unknown initial bytes are
masked; generated partial images are analysis inputs, not flashing files.
"""
from pathlib import Path
import importlib.util
import sys
import hashlib
import json
import argparse

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[2]
CANON = WORK / 'AirRemote_TTL_C_AIR2_P8'
HELPERS = HERE / 'helpers'
OPAQUE_FF_SUFFIX_SHA256 = '775ca7d84bf15f7b59b6c0a1c755aa7560d9325f57e49ac94a48ee4f55df9a56'
BASE, END = 0x4000, 0x1FC00
MODELS = {
    'N': ('c5', '4fa0d7c1ae8201910e0586eef30feadb9230e3c30c7b67b8dc4c2d344dea5591', 2125208),
    'S': ('a6', '707b65d9cb6ea6c320976e5a6244de05b1f0856ab9c7ddc5008fe739337b9737', 2125208),
    'F': ('a5', '455b3f8eb74c2a598d5bd679d3450e9850860eae8de84362da71edb4896e4e6a', 2125432),
    'O': ('a4', '80ae4cac56c6bb7c363062d3ed7927373e4b7a907df8abbc2fed6731621a52b5', 2125432),
}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(data):
    return hashlib.sha256(data).hexdigest()


def need(ok, message):
    if not ok:
        raise ValueError(message)


def crc16(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def write_same_or_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    need(not path.exists() or path.read_bytes() == data, 'Different output exists: ' + str(path))
    if not path.exists():
        with path.open('xb') as handle:
            handle.write(data)


def inspect(firmware_root=None, selected_models=None):
    container = load('multi_air2_container', HELPERS / 'container.py')
    codec_module = load('multi_air2_codec', HELPERS / 'reference_codec.py')
    codec = codec_module.ReferenceCodec()
    # This fingerprint was independently derived from the recovered C11 FF
    # suffix, then matched in all four pinned vendor updater resources. No
    # Canon firmware is needed to rebuild a non-Canon port.
    firmware_root = Path(firmware_root) if firmware_root else WORK / 'air_remote_ttl'
    selected_models = tuple(selected_models) if selected_models else tuple(MODELS)
    need(all(model in MODELS for model in selected_models), 'Unknown model')
    rows = {}
    for model, (version, fingerprint, start) in MODELS.items():
        if model not in selected_models:
            continue
        relative = ('air_remote_ttl/air-remote-ttl-%s-firmware-%s-win/'
                    'Air-Remote-TTL-%s-Firmware-%s.exe') % (model.lower(), version, model, version.upper())
        outer = (firmware_root / Path(relative).relative_to('air_remote_ttl')).read_bytes()
        need(sha(outer) == fingerprint, 'Unpinned input: ' + model)
        end = start + container.HEX_END - container.HEX_START
        image = container.HexImage(outer[start:end])
        need(image.layout_sha256() == container.LAYOUT_SHA256, 'HEX layout: ' + model)
        need(image.spans() == container.SPANS, 'HEX spans: ' + model)
        dense = bytes(image.memory[a] for a in range(BASE, END))
        need(sha(dense[0xC000:]) == OPAQUE_FF_SUFFIX_SHA256, 'Opaque high tail differs: ' + model)
        plain = b'\0\0' + codec.decode(0x4002, dense[2:0xC000]) + b'\xff' * (END - 0x10000)
        mask = b'\0\0' + b'\1' * (END - BASE - 2)
        need(codec.encode(0x4002, plain[2:0xC000]) == dense[2:0xC000], 'Codec roundtrip: ' + model)
        stored_crc = int.from_bytes(plain[0x50:0x52], 'little')
        calculated_crc = crc16(plain[2:0x50] + plain[0x52:0x100])
        need(stored_crc == calculated_crc, 'Stock header CRC: ' + model)
        non_ff_end = max(i for i, value in enumerate(plain[0x100:0xC000], 0x100) if value != 255) + BASE + 1
        row = {
            'model': 'Air Remote TTL-' + model, 'version': version.upper(),
            'source': relative, 'source_size': len(outer), 'source_sha256': fingerprint,
            'hex_start': start, 'hex_end': end, 'hex_sha256': sha(image.text),
            'hex_layout_sha256': image.layout_sha256(), 'hex_spans': image.spans(),
            'outside_hex_sha256': sha(outer[:start] + outer[end:]),
            'partial_plaintext_sha256': sha(plain), 'known_mask_sha256': sha(mask),
            'known_start': 0x4002, 'base': BASE, 'end_exclusive': END,
            'header_crc_stored': stored_crc, 'header_crc_calculated': calculated_crc,
            'header_crc_xor': 0, 'header_model_le16': int.from_bytes(plain[0x52:0x54], 'little'),
            'header_version_le16': int.from_bytes(plain[0x54:0x56], 'little'),
            'last_non_ff_end_exclusive_below_10000': non_ff_end,
            'high_tail_opaque_equal_known_C11_ff': True, 'codec_roundtrip_exact': True,
            'first_two_plaintext_bytes_unknown': True, 'updater_executed': False,
            'hardware_accessed': False, 'air2_port_implemented': False,
            'scope': 'Stock-only analysis; no modified executable is generated.',
        }
        folder = HERE / 'stock' / model
        write_same_or_new(folder / 'original.hex', image.text)
        write_same_or_new(folder / 'original.base4000.partial.bin', plain)
        write_same_or_new(folder / 'original.known_mask.bin', mask)
        write_same_or_new(folder / 'profile.json', (json.dumps(row, indent=2) + '\n').encode('utf-8'))
        rows[model] = row
    if set(selected_models) == set(MODELS):
        write_same_or_new(HERE / 'stock_inventory.json', (json.dumps(rows, indent=2) + '\n').encode('utf-8'))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path,
                        help='Directory containing the original per-model updater folders')
    parser.add_argument('--model', choices=tuple(MODELS), action='append', help='Process only this model; may be repeated')
    args = parser.parse_args()
    rows = inspect(args.firmware_root, args.model)
    print(json.dumps({k: {'source_sha256': v['source_sha256'],
                         'code_data_end': hex(v['last_non_ff_end_exclusive_below_10000']),
                         'header_crc': hex(v['header_crc_stored']),
                         'codec_roundtrip_exact': v['codec_roundtrip_exact']} for k, v in rows.items()}, indent=2))
