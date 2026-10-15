#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Caimankekw
"""Inspect the branch-pinned original updater as data; Python 3.9+, stdlib only.

Adapted from shared/inspect_variants.py. No updater execution or hardware I/O.
The partial BIN is an analysis artifact, never a flashable firmware image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from helpers.container import HexImage, LAYOUT_SHA256, SPANS
from helpers.reference_codec import ReferenceCodec

ROOT = Path(__file__).resolve().parents[1]
BASE, END = 0x4000, 0x1FC00
TRANSFORM_START, TRANSFORM_END = 0x4002, 0x10000
OPAQUE_FF_SUFFIX_SHA256 = "775ca7d84bf15f7b59b6c0a1c755aa7560d9325f57e49ac94a48ee4f55df9a56"
# SHA-256 of the complete original stock profile serialized as sorted compact
# JSON. Reject edits to model.json which weaken hashes, coordinates or claims.
PROFILE_PINS = {
    "Air Remote TTL-N": "e7bbd75b96a7c910a27a4397611f36ebafe41c4ac47f32cbab2680d04edf9823",
    "Air Remote TTL-S": "b882319cb0a721e20b056297f9cd909559adc7d07345dc04b5a56a2d3d59e0d3",
    "Air Remote TTL-F": "53d1c89c1795bbe3c81d4d2834ff31c2a9da96726e66776dbb29d393b5892e2a",
    "Air Remote TTL-O": "a3fcda1ae892d313cae5da5d47ec927c29d6376209d309eec3c548f168656cff",
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def validate_profile(profile):
    need(isinstance(profile, dict), "model.json must contain the complete stock profile")
    need(isinstance(profile.get("model"), str), "Unsupported model in model.json")
    expected = PROFILE_PINS.get(profile.get("model"))
    need(expected is not None, "Unsupported model in model.json")
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    need(sha(canonical) == expected, "model.json does not match the pinned original profile")
    return profile


def load_profile():
    """The branch root is fixed by this script, never the working directory."""
    return validate_profile(json.loads((ROOT / "model.json").read_text(encoding="utf-8-sig")))


def crc16(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def verify_original(outer, profile):
    """Return byte-exact stock artifacts after all independent gates pass."""
    validate_profile(profile)
    need(len(outer) == profile["source_size"], "Original EXE size mismatch")
    need(sha(outer) == profile["source_sha256"], "Original EXE SHA-256 mismatch (wrong model or changed file)")
    start, end = profile["hex_start"], profile["hex_end"]
    hex_bytes = outer[start:end]
    need(sha(hex_bytes) == profile["hex_sha256"], "Original HEX SHA-256 mismatch")
    outside_sha = sha(outer[:start] + outer[end:])
    need(outside_sha == profile["outside_hex_sha256"], "Bytes outside the HEX resource differ")
    image = HexImage(hex_bytes)
    layout_sha = image.layout_sha256()
    need(layout_sha == LAYOUT_SHA256 == profile["hex_layout_sha256"], "HEX layout mismatch")
    spans = image.spans()
    need(spans == SPANS and [list(span) for span in spans] == profile["hex_spans"], "HEX sparse spans mismatch")
    dense = bytes(image.memory[address] for address in range(BASE, END))
    tail_sha = sha(dense[TRANSFORM_END - BASE:])
    need(tail_sha == OPAQUE_FF_SUFFIX_SHA256, "Opaque high tail does not match the known FF suffix")
    codec = ReferenceCodec()
    # 0x4000 and 0x4001 are unknown: zero placeholders, not recovered zeros.
    # Only [0x4002,0x10000) is transformed. High FF is admitted by the pin above.
    plain = (b"\0\0" + codec.decode(TRANSFORM_START, dense[2:TRANSFORM_END - BASE])
             + b"\xff" * (END - TRANSFORM_END))
    mask = b"\0\0" + b"\1" * (END - BASE - 2)
    need(codec.encode(TRANSFORM_START, plain[2:TRANSFORM_END - BASE]) == dense[2:TRANSFORM_END - BASE],
         "Codec roundtrip mismatch")
    stored_crc = int.from_bytes(plain[0x50:0x52], "little")
    calculated_crc = crc16(plain[2:0x50] + plain[0x52:0x100])
    need(stored_crc == calculated_crc, "Stock header CRC mismatch")
    non_ff_end = max(i for i, value in enumerate(plain[0x100:0xC000], 0x100) if value != 255) + BASE + 1
    observed = {
        "source_size": len(outer), "source_sha256": sha(outer),
        "hex_start": start, "hex_end": end, "hex_sha256": sha(image.text),
        "hex_layout_sha256": layout_sha, "hex_spans": [list(span) for span in spans],
        "outside_hex_sha256": outside_sha, "partial_plaintext_sha256": sha(plain),
        "known_mask_sha256": sha(mask), "known_start": TRANSFORM_START,
        "base": BASE, "end_exclusive": END,
        "header_crc_stored": stored_crc, "header_crc_calculated": calculated_crc,
        "header_crc_xor": stored_crc ^ calculated_crc,
        "header_model_le16": int.from_bytes(plain[0x52:0x54], "little"),
        "header_version_le16": int.from_bytes(plain[0x54:0x56], "little"),
        "last_non_ff_end_exclusive_below_10000": non_ff_end,
        "high_tail_opaque_equal_known_C11_ff": True, "codec_roundtrip_exact": True,
        "first_two_plaintext_bytes_unknown": True, "updater_executed": False,
        "hardware_accessed": False, "air2_port_implemented": False,
    }
    for key, value in observed.items():
        need(value == profile[key], "Stock profile mismatch: " + key)
    report = {
        "format": "air-remote-original-inspection-v1", "model": profile["model"],
        "version": profile["version"], "all_checks_passed": True,
        "source_sha256": observed["source_sha256"], "input_path_recorded": False,
        "opaque_ff_suffix_sha256": tail_sha,
        "address_ranges": {
            "unknown_zero_placeholders": [BASE, TRANSFORM_START],
            "directly_transformed": [TRANSFORM_START, TRANSFORM_END],
            "known_ff_by_fixed_opaque_fingerprint": [TRANSFORM_END, END],
        },
        "range_endpoints": "exclusive", "mask_values": {"unknown": 0, "known": 1},
        "partial_bin_is_flashable": False, "arbitrary_full_range_decode_supported": False,
        "original_hex_preserves_sparse_layout_and_configuration": True,
        "updater_executed": False, "hardware_accessed": False,
        "outputs": {
            "original.hex": observed["hex_sha256"],
            "original.base4000.partial.bin": observed["partial_plaintext_sha256"],
            "original.known_mask.bin": observed["known_mask_sha256"],
        },
    }
    return {
        "original.hex": image.text, "original.base4000.partial.bin": plain,
        "original.known_mask.bin": mask, "profile.json": json_bytes(profile),
        "inspection.json": json_bytes(report),
    }


def require_new_output(output):
    need(not output.exists() and not output.is_symlink(),
         "Output already exists; choose a new --output directory")


def write_outputs(output, artifacts):
    """Only exclusive creation; leave any partial results in place on failure."""
    output = Path(output)
    require_new_output(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, content in artifacts.items():
        with (output / name).open("xb") as handle:
            handle.write(content)


def inspect_original(original, output):
    output = Path(output)
    require_new_output(output)
    profile = load_profile()
    artifacts = verify_original(Path(original).read_bytes(), profile)
    write_outputs(output, artifacts)
    return json.loads(artifacts["inspection.json"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True, help="Path to the exact original EXE pinned by root model.json")
    parser.add_argument("--output", type=Path, required=True, help="New local output directory; existing paths are refused")
    args = parser.parse_args()
    try:
        report = inspect_original(args.original, args.output)
    except (OSError, ValueError, KeyError) as exc:
        print("Inspection refused: " + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
