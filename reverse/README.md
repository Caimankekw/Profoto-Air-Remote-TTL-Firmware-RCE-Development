# Sony A6 original firmware notes

This directory documents bounded reverse engineering of **Air Remote TTL-S A6**. [original.pseudocode.c](original.pseudocode.c) is human-written C-like pseudocode with address evidence. It is **not the manufacturer's complete C source, cannot be compiled into the original firmware, and is not flashable**. Names, types and structured flow are reconstructed explanations. Opaque calls preserve the boundaries of work not recovered here.

[中文说明](README.zh-CN.md)

| Published file | Purpose |
| --- | --- |
| [model.json](../model.json) | Exact original stock identity profile and extraction fingerprints |
| [original_contract.json](original_contract.json) | Selected original RAM, key, UI, clock, queue and NVM facts |
| [source_map.json](source_map.json) | PIC18 byte addresses, short entry signatures, stock span SHA-256 and pseudocode block links |
| [provenance.json](provenance.json) | Input fingerprints, selection method and old-candidate comparison |

No updater executable, firmware BIN/HEX, full listing, device capture or absolute workstation path is included. Provenance paths identify earlier research inputs and are not dependencies of this branch. Selected facts are carried in the public contract and source map. Reproducing them from firmware requires a separately obtained matching original updater and the repository's read-only inspection tooling.

## Recovered boundaries

| Area | Original anchors | What the evidence supports |
| --- | --- | --- |
| Startup and loop | `4102 → 4252 → 6174`, `4D42`, `4E94` | ROM initialization, board/object entry and foreground call order |
| Clock | `6972`, `69CC..69D8` | Full 16-bit count at RAM `106:107`; strict `delta > divisor`, remainder discarded after update |
| Keys | `4EE2`, `930E`, `5348`, `A0C8` | Eleven four-byte objects, three-sample debounce, 250/650-count thresholds |
| Three-group UI | `5CD8`, `6DDE`, `7584`, `51DE` | A/B/C or ALL, original relative/FEC values, LCD snapshot and serial service |
| Radio | `7490 → 9516 → A158 → 5C08 → 5DA4` | Relative frame builder, native queue and normal `RSGT1` serialization |
| NVM | `835E`, `81A6`, `9840`, `9FE4` | Descriptor, logical slot-address arithmetic and flash primitives |
| Camera/HSS boundary | `4108..4252`, `6BB0..6DDE`, `A586..A5E8` | Observed interrupt/camera/exclusive-radio regions; **not a complete HSS algorithm** |

Addresses are hexadecimal PIC18 **byte addresses**. JSON ranges include the start and exclude the end. Source-map spans are selected evidence ranges, not automatically complete functions. Range hashes and short signatures were read from the original stock bytes; semantic labels additionally use static interpretation and the identified research inputs. Pseudocode omits calling conventions, register clobbers and some side effects. Its numeric rendering block is a value-selection sketch, not a replacement renderer.

The native mode object is at RAM `0193`, through `D2:D3`; `0=TTL`, `1=MAN`. Original FEC lives at `197..199`, manual-relative values at `EC..EE`; selector `C1` uses `1/2/3/7`. HEAD `DB` and MODEL `F3` use the low three bits. Original ALL selection clears its selection boxes. Packet-level group acceptance does not imply a six-group stock UI. No added six-group policy, absolute-power command, hook, adapter, chord feature or new NVM format is represented as original firmware.

The queue at `E6..EB` has 100 bytes of backing at `[0400,0464)`. A normal record is marker zero plus a 16-byte frame, admitted only at used count at most 83. `A158` reads a bank-0 source address from `076`; success is local queue admission, not a receiver acknowledgement. It does not mask interrupts. The bounded ISR direct-flow audit reaches other queue producers and abort helpers, so a whole record must not be assumed atomic. `D8` is an observed exclusive-radio gate, not proof of all camera-busy phases.

## Evidence limits

`4000..4001` remains unknown; zeros are placeholders. `[4002,10000)` is directly transformed. `[10000,1FC00)` is FF fill supported by a fixed opaque tail fingerprint for the exact updater family, **not arbitrary high-address decryption**. `model.json` is the original stock profile verbatim; `air2_port_implemented: false` belongs to that stock snapshot.

The older candidate covers `[4000,10000)`, 49,152 bytes, SHA-256 `b5d7c9b199cc1a705514c028d609e31bb8b6fb55813cdc2ab1fcba898be7cee5`. Shared stock covers `[4000,1FC00)`, 113,664 bytes, SHA-256 `abed888029102baea3a3f003ee40d8ab27119a3b1c3ff988342dbfaf8437984b`. Their known overlap `[4002,10000)` was compared byte for byte and is identical. The different full-file hashes reflect different lengths/ranges; neither unknown first word is recovered.

Native counts are not calibrated milliseconds. The 250-count callback `AF5A` is a return; the 650-count path is `A134 → 6A96`. Threshold replay used a callback boundary and does not establish the complete repeating-hold schedule. `DC` is not proven to mean channel editing.

The original logical journal is `[1F800,1FC00)`: 256 four-byte slots, descending from `1FBFC`. Logical addressing does not prove physical erase geometry or complete journal commit/recovery behavior. Flash helpers unconditionally set `FD0.7` and `FF2.7` on return, not the prior interrupt state.

The ISR audit is a direct-flow overapproximation, not a proof of input feasibility, all runtime control flow or physical HSS correctness. `4250` is the fast return; `41B8` is the second word of a call and is not a separate ISR entry. No updater was executed and no hardware, USB, camera, radio or exposure was tested during this publication work. Complete manufacturer C sources, bootloader recovery and a complete HSS algorithm remain outside the recovered scope.
