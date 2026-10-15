# Read-only original updater inspection

English | [简体中文](README.zh-CN.md)

Requires Python 3.9 or newer, standard library only. Supply the original vendor
EXE for this branch from your own local copy. The EXE may be anywhere on disk;
no second vendor file, Canon updater, installation, or device is required.

From the repository root:

```powershell
python tools/inspect_original.py --original "D:\Firmware\original.exe" --output outputs/inspection-01
python tests/test_inspect_original.py
python tests/test_inspect_original.py --original "D:\Firmware\original.exe" --other-original "D:\Firmware\another-model.exe"
```

The tool always reads `model.json` beside the repository's `tools` directory,
independent of the current working directory. That file must contain the complete
unchanged stock profile for this branch. There is no model, profile, hash-bypass,
or resource-offset override. A fingerprint of the complete profile rejects edits
that would weaken the checks; this is reproducibility validation, not a signature
or protection against edits to the source itself.

The tool checks EXE size and SHA-256, resource and surrounding-byte SHA-256,
every Intel HEX checksum, sparse address spans and record layout, the transform
manifest and table, the fixed opaque FF-tail fingerprint, codec roundtrip,
header CRC/model/version, last non-FF address, and recovered output hashes.

Addresses below are absolute MCU byte addresses; every end is exclusive:

| Range | Meaning |
| --- | --- |
| `[0x4000,0x4002)` | Plaintext unknown; two `00` placeholders with mask `00 00`. These are not recovered zero bytes. |
| `[0x4002,0x10000)` | Directly decoded by the pinned address-dependent byte transform. |
| `[0x10000,0x1FC00)` | Known `FF` only because the entire opaque tail matches its fixed known-FF fingerprint. No arbitrary tail transform is claimed. |

The output directory contains the original `original.hex`,
`original.base4000.partial.bin`, `original.known_mask.bin`, `profile.json`, and
`inspection.json`. The first four reproduce the stock reference artifacts byte
for byte. The partial BIN starts at `0x4000` and has 113,664 bytes. Mask `01`
means known; `00` means unknown. Only the original HEX retains the additional
configuration bytes and sparse gaps. **The partial BIN is for analysis and is
not a flashable firmware image.**

Output uses a new directory. Every existing output path is refused, including
an identical prior run. Validation finishes before any output is created;
exclusive creation prevents overwrites. An interrupted write may leave partial
results; the tool never deletes them. Choose another new directory to retry.
Reports contain no supplied local input path. Keep generated output and test
scratch directories local; they are not source material for publication.

The tests run strict parser, transform-integrity/range, profile-tampering and
output-conflict checks. Passing `--original` adds full extraction and input
mutation tests; `--other-original` additionally checks wrong-model rejection.
Test scratch directories remain under `outputs/` for inspection.

No EXE is executed, modified or generated. No network or USB access occurs.
Successful offline checks do not establish device acceptance or vendor approval.

Authored inspection/adaptation code and explanatory text: Copyright (C) 2026
Caimankekw, **AGPL-3.0-only**; see the repository's `LICENSE`. This tool adapts
the project's `shared/inspect_variants.py`, strict `HexImage` parser, and
`ReferenceCodec`. The bundled table contains derived byte-transform parameters,
not a firmware image. Original Profoto firmware, recovered vendor instructions,
updater/loader code and other third-party material retain their own copyrights
and terms. This project does not claim authorship of or grant redistribution
rights to those materials. Generated extraction files do not acquire an AGPL
relicense merely by using this tool.
