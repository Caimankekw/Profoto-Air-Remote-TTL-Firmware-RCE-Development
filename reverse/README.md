# Fujifilm A5 original firmware reverse engineering

[中文](README.zh-CN.md) · [Identity profile](../model.json) · [Contract](original_contract.json) · [Evidence index](provenance.json)

This branch documents selected original **Air Remote TTL-F A5** behavior. The C-like files are explanatory reverse engineering, not the manufacturer's complete C source and not compilable firmware. `native_*` and `opaque_*` stand for original routines whose omitted internals must not be treated as recovered implementations. AIR2-M2 development is a separate branch.

| Module | Original byte-address anchors | Coverage |
|---|---|---|
| [Keyboard and clock](pseudocode/keyboard_clock.c) | `48EA`, `97C0`, `A50E`, `581A`, `7050`, `B202`, `AB22` | Object sampling, dispatch boundaries, native clock arithmetic |
| [Three-group UI](pseudocode/ui_abc.c) | `7ED4`, `9EBE→6492`, `8D7E`, `7AD2`, `6E7E`, `A6BA` | TTL/MAN, A/B/C/ALL, callbacks, LCD ABI |
| [Radio](pseudocode/radio.c) | `B2CE`, `9562`, `A60A`, `84D6`, `7174`, `864C` | Type 2, 16-byte body, original admission and framing |
| [Startup and NVM](pseudocode/nv_startup.c) | `5F6E`, `4C3A`, `6AAC`, `9BAC`, `A3DE` | Initialization, journal descriptor and native write sequence |
| [Camera/HSS boundaries](pseudocode/hss_boundaries.c) | `4108..41C4`, `5D42..5E6A`, `614C..62F4` | Audited original entry/call boundaries only |

`VERIFIED` means supported by decoded original instructions, pinned preimages or the cited offline instruction audit. `INFERRED` marks semantic interpretation, such as physical key labels or radio sleep meaning. `UNKNOWN` marks unresolved behavior. These categories do not establish physical-camera, RF, lamp or HSS performance.

The original `A60A` requests **16**, not 17, from admission `9562`: `requested <= 31 && count + requested < capacity`. It then writes marker 0 and 16 body bytes. A development preflight for all 17 bytes is a separate change. Original Flash helpers clear `FD0.7` / `FF2.7`, then **unconditionally set both** after starting the operation; preserving their earlier state is also a development change. Original UI has A/B/C and ALL, with no native D/E/F page.

The source identity and container range are pinned in `model.json`, copied unchanged from the stock profile. The analysis image spans `[0x4000,0x1FC00)`. Its first word `[0x4000,0x4002)` remains unknown; placeholder zeros are not recovered instructions. The reference codec reads `[0x4002,0x10000)`. High-tail FF interpretation on `[0x10000,0x1FC00)` relies on matching opaque encoded bytes to a known FF reference, not independent decoding. The observed last non-FF byte below `0x10000` ends at `0xB2E0` exclusive; this is not proof of executable boundaries or free flash ownership. All windows in `provenance.json` lie inside the decoded interval.

The original HEX spans `[0x4000,0x1FC10)` and `[0x1FFF0,0x20000)`. Its 32 bytes beyond the analysis image and its address gap are not covered by the partial plaintext. This is not a complete firmware decode.

The evidence index gives original workspace-relative source identities and SHA-256 hashes, plus exact half-open byte windows and hashes over the local stock analysis image. These paths are historical provenance, not bundled runtime dependencies. Candidate linear listings may decode data as instructions, so only reviewed windows are summarized. The full manufacturer updater, HEX/BIN images, large listings and device captures are not included.

No EXE, device, USB or network action was run to produce this package. The HSS algorithm, real time unit, bootloader behavior and all indirect RAM ownership are not reconstructed. Existing AIR2 qualification claims are not imported into this original-only contract.
