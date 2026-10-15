# Olympus A4 original firmware reverse engineering

[中文](README.zh-CN.md) · [Identity profile](../model.json) · [Contract](original_contract.json) · [Evidence index](provenance.json)

This branch documents selected original **Air Remote TTL-O A4** behavior. The C-like files are explanatory reverse engineering, not the manufacturer's complete C source and not compilable firmware. `native_*` and `opaque_*` retain unresolved original internals. AIR2-M2 development belongs to a separate branch.

| Module | Original byte-address anchors | Coverage |
|---|---|---|
| [Keyboard and clock](pseudocode/keyboard_clock.c) | `5036`, `92FC`, `9DF4`, `596E`, `AB2E`, `669C` | Key history/flags, 250/650-count callbacks, timestamp semantics |
| [Three-group UI](pseudocode/ui_abc.c) | `6A62`, `98D8→609A`, `86D6`, `742E`, `688E`, `A10E` | TTL/MAN, A/B/C/ALL, native ranges, LCD ABI |
| [Radio](pseudocode/radio.c) | `ABD8`, `919E`, `9F1E`, `936C`, `82B0` | Type 2, original admission, 16-byte body and marker |
| [Startup and NVM](pseudocode/nv_startup.c) | `69CA`, `5E1C`, `5520`, `A66C`, `962C`, `9E1A` | Startup ordering, journal packing, write behavior |
| [Camera/HSS boundaries](pseudocode/hss_boundaries.c) | `4108..4178`, `67E8..688E`, `466A`, `75AC`, `8A92` | IRQ, camera receive and forced-mode call boundaries |

`VERIFIED` denotes support from decoded original instructions, pinned preimages or the cited offline audit. `INFERRED` denotes semantic interpretation, including physical key labels and delta units. `UNKNOWN` denotes unresolved behavior. No category establishes physical-camera, RF, lamp or HSS performance.

The original `9F1E` requests **16** from `919E`, whose rule is `requested <= 31 && count + requested < capacity`, then appends marker 0 and 16 body bytes. A separate 17-byte preflight is an AIR2 change. Original write/erase helpers unconditionally set `FD0.7` / `FF2.7` after the operation starts; they do not preserve the previous enable state. The original expiry path at `7F7E` is MAN-only. Extending it to TTL, adding D/E/F, temporarily inhibiting radio around a mode change, and recomputing boot pending state are development behavior, not stock reconstruction.

The unchanged `model.json` pins the stock profile. The analysis image spans `[0x4000,0x1FC00)`: the first word `[0x4000,0x4002)` is unknown and placeholder zeros are not recovered instructions. The reference codec reads `[0x4002,0x10000)`. High-tail FF interpretation on `[0x10000,0x1FC00)` depends on an opaque encoded-byte fingerprint matching a known FF reference, not independent decoding. The last observed non-FF byte below `0x10000` ends at `0xABF0` exclusive; this proves neither executable extent nor free flash ownership. Every provenance window is within the decoded interval.

The evidence index gives original workspace-relative source identities, SHA-256 hashes and exact half-open byte windows hashed from the pinned stock analysis image. Source paths are historical provenance, not runtime dependencies. Only reviewed instruction windows are summarized; a linear candidate listing can misinterpret data as code. Manufacturer EXE/HEX/BIN files, large listings and device captures are omitted.

No EXE, device, USB or network action was run to assemble this package. The 250/650 thresholds must not be called milliseconds. Complete HSS timing, analog multi-key behavior, bootloader ownership and unproven interrupt nesting remain unknown. AIR2 qualification is not an original-firmware proof.
