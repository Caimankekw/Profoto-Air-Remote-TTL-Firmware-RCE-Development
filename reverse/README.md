# Nikon C5 original firmware notes

This directory documents bounded reverse engineering of **Air Remote TTL-N C5**. [original.pseudocode.c](original.pseudocode.c) is human-written C-like pseudocode with address evidence. It is **not the manufacturer's complete C source, cannot be compiled into the original firmware, and is not flashable**. Function names, types and structured control flow are explanatory reconstructions. Opaque calls mark work that has not been reconstructed here.

[中文说明](README.zh-CN.md)

| Published file | Purpose |
| --- | --- |
| [model.json](../model.json) | Exact copy of the original stock identity profile; updater/HEX/dense-image fingerprints and extraction offsets |
| [original_contract.json](original_contract.json) | Selected original RAM, UI, clock, radio and NVM facts |
| [source_map.json](source_map.json) | PIC18 byte addresses, short entry signatures, stock span SHA-256 and pseudocode block links |
| [provenance.json](provenance.json) | Input fingerprints, selection method and verification limits |

No updater executable, firmware BIN/HEX, full listing, device capture or absolute workstation path is included. Archival relative paths in the provenance identify earlier research inputs; those files are not dependencies of this branch. The published contract and source map carry the selected facts. Reproduction from firmware requires a separately obtained original updater matching `model.json` and the repository's read-only inspection tooling.

## Recovered boundaries

| Area | Original anchors | What the evidence supports |
| --- | --- | --- |
| Startup and loop | `4102 → 417E → 56DE`, `4CF6` | Runtime initialization, original foreground call order and camera gate |
| Clock | `7124`, `716E..7174` | Full 16-bit count at RAM `11B:11C`; strict `delta > divisor`, remainder discarded after update |
| Keys | `4D44`, `8E62`, `4ECC`, `9BA6` | Eleven four-byte objects; history retains bit 7; three-sample debounce; 250/650-count hold thresholds |
| Three-group UI | `946E → 5986`, `6928`, `6F44` | A/B/C and ALL selection, TTL FEC or manual-relative values, native signed-tenths rendering |
| Radio | `6ECC → 8FB0 → 9D54`, `5E34` | Relative commands, a zero marker plus 16-byte queue record, normal `RSGT1` transport |
| NVM | `6088..609E → 7FC4`, `91C2`, `9B0E` | Original journal descriptor and flash word/erase primitives |
| Camera/timing | `4108`, `5D74`, `65C2`, `6CD0`, `9A02`, `A0AE`, `A77A` | Observed interrupt, camera state, pulse and RX boundaries; **not a complete HSS algorithm** |

Addresses are hexadecimal PIC18 **byte addresses**. All JSON ranges are start-inclusive/end-exclusive. Source-map spans are selected evidence ranges, not automatically whole functions. Their hashes and entry bytes were read from the original stock image; semantic summaries additionally depend on static interpretation and the identified research inputs. Pseudocode omits register clobbers, calling conventions and some side effects. Numeric rendering is explicitly a value-selection sketch.

The original mode object is normally at RAM `01B1`, selected through `49:4A`: mode `0=TTL`, `1=MAN`; A/B/C FEC occupies offsets `4..6`. Original manual-relative values occupy `99..9B`. HEAD `4C` and MODEL `50` retain low-three-bit group meanings. The original UI has three groups. No added six-group state, chord policy, absolute-power command, hook, adapter or new persistence format is represented as a stock feature.

The queue has capacity 100 bytes and uses 17 bytes per ordinary record, so admission requires used count at most 83. A successful `9D54` result means local admission; it does not establish receiver acknowledgement, RF completion or exposure success. The original `7A12` FEC command `25` is separate from relative manual commands `06/07/0D/0E`.

## Evidence limits

`4000..4001` remains unknown and is represented by two zero placeholders. `4002..10000` is the directly transformed region. The FF fill for `[10000,1FC00)` is supported by matching the fixed opaque high-tail fingerprint for this exact updater family; it is **not arbitrary high-address decryption**. The dense partial image is 113,664 bytes, including the unknown placeholders. `model.json` preserves the original stock-only profile verbatim; its `air2_port_implemented: false` field describes that stock snapshot.

The nominal approximately 1 kHz design is an inference from clock/divisor setup, not a physical millisecond calibration. The `7FFF` mask belongs to a separate encoded-deadline path, not the raw 16-bit tick. The extra PORTE.1 input's physical user-facing role is unconfirmed.

The original journal logical range is `[1F800,1FC00)`. Its complete slot selection, commit and recovery state machine has not been recovered here. The flash helpers unconditionally set `FD0.7` and `FF2.7` on return; they do not restore the previous interrupt-enable state. This material does not prove physical erase geometry or power-loss behavior.

Camera/HSS entries and selected byte ranges do not recover the complete HSS algorithm or prove physical equivalence. No updater was executed and no device, USB, camera, radio or exposure was tested during this publication work. No complete manufacturer source tree, original build system or bootloader reconstruction is claimed.
