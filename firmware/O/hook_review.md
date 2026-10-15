# Olympus O outer-hook review

Static contract, 2026-10-15. All addresses are PIC18 byte addresses. The recorded preimages match `../shared/stock/O/original.base4000.partial.bin`; every byte has known-mask value 1. Original SHA256: `84645f098eeab93dd41d150015c7c642207037b7605b937b0a13388df1805976`. The initial word is still unknown. `hook_contract.json` contains the machine-readable boundaries and constraints; `keyboard_contract.json` retains the broader keyboard map.

**Two closure issues require explicit handling:** native idle branch `7FBE` runs only in MAN, and the UI-timeout path after service `58E0` can overwrite a freshly rendered LCD. These are proved branches, not hypothetical timer behavior.

仅静态审查；未改固件、未运行升级器/USB、未生成可刷包。物理按键标签来自 handler 语义，未经 Olympus 实物验证。Static review only; wrapper machine-code replay, RAM proof and hardware validation remain integration work.

## Exact outer boundaries

| Purpose | Address / original bytes | Original instruction | Wrapper and continuation |
|---|---|---|---|
| Startup | `57BC: 9F EC 46 F0` | `CALL 8D3E` | Replacement CALL; original first, save its return context, `core.init`, restore, RETURN `57C0` |
| Normal press | `5C12: 00 0E 00 01` | `MOVLW 0; MOVLB 0` | Replacement GOTO; handled RETURN to `5A3C`; fallback replays both instructions and GOTO `5C16` |
| Relative/power delta | `86D6: 00 01 EA 6F` | `MOVLB 0; MOVWF EA` | Replacement GOTO; input W signed delta; handled RETURN, fallback replay then GOTO `86DA` |
| Main service | `58E0: D6 EC 3A F0` | `CALL 75AC` | Replacement CALL; original first, preserve post-return context around service, RETURN `58E4` |
| Native MAN idle | `7FBE: 12 EC 36 F0` | `CALL 6C24` | Replacement CALL; original first, preserve post-return context around `idle_expired`, RETURN `7FC2` |
| Final LCD overlay | `5912: CD EC 42 F0` | `CALL 859A` | Replacement CALL; preserve arguments/context, redraw normal UI, restore, tail GOTO `859A`; original return `5916` |

The parent initially selected redraw in the `58E0` wrapper and no LCD hook. Rechecking the full intervening path found the overwrite described below. Therefore `5912` is a required correction for same-pass overlay correctness unless an equivalent later redraw is implemented; it is not represented here as already implemented. No `5938` transport hook is necessary with final overlay before the dirty comparison.

## Startup and actual configuration pointer

`57A2 MOVLW99;57A4 MOVWF F3;57A6 MOVLW01;57A8 MOVWF F4;57AA CALL5520` supplies `0x0199`. At `5520 MOVFF0F3,07E;5524 MOVFF0F4,07F`, RAM `7E:7F` becomes the actual config pointer `0x0199`. Mode is config+0, FEC A/B/C config+4/+5/+6 (`19D..19F`).

`57AE..57BA` next supplies object `0x40` and config `0x0199` to `8D3E`; `8D5A..8D66` clears config+1 and the routine finishes native object initialization. Hooking the call at `57BC` after this original routine gives core init the completed native snapshot. `57C0` is the recurring loop head and must not be used as unconditional one-time init. Core magic is `A8`; private RAM must be explicitly initialized, not assumed zero from native startup clearing.

## Normal press: correct pointer and return frame

The pointer at `5C12` is **RAM `F2:F3`**, not `1E:1F`:

`5A30/5A34: 1E9:1EA -> F4:F5` → `5A38 CALL80F4` → original permission helpers `A3E0`, `9F42`, `A838` → `8138` tests normal UI `082==0` → `8110/8114: F4:F5 -> F2:F3` → `8118 GOTO5C12`.

A handled wrapper RETURN therefore consumes the existing CALL `80F4` frame, reaching `5A3C`; `5A40` still sets history bit7 and `5A42 RETLW0` returns to consumer `9DF4`. A new CALL at the function entry would change this stack contract, so replace the two displaced instructions with a GOTO.

Dispatch slots `10C` A and `110` B to `select_row` W1/W2. Dispatch `114` C, `118` MODEL, `11C` HEAD to `secondary_press` W1/W2/W4. Other keys, including native MODE slot `100`, replay the original path. Once initialized core owns a key, a core refusal must not fall through to its original native effect.

## C / MODEL / HEAD: suppress press, timed callbacks and release

At the owned normal press, skip the original handler and OR **slot+1 flags with `0x30`**: addresses `115`, `119`, `11D`. Preserve history and timestamp. This covers the recorded normal state machine without separate release/hold hooks:

1. Press suppression is the handled RETURN from `5C12`; the original select/model/head handler never executes.
2. At `59BA RCALL5A8E`, FSR2 points to slot+1. `59BC BTFSC INDF2,5;59BE RETURN` exits before both the 250-count `ABC2` callback (`59D4`) and 650-count `9ED6` callback (`5A00`).
3. At release, `5A5E RCALL5A8E;5A60 BTFSC INDF2,4;5A62 BRA5A76` skips `5A72 CALL83B0`.
4. `5A76..5A8C` still resets flags to `08`, timestamp to zero and history to zero, so the next press can rearm.

`9936 MOVLWBB;9938 ANDWF slotflags,F` preserves bits4/5 but clears bit6. Consequently bit6 alone is not sufficient. Timed thresholds 250/650 are native counter values; this review does not label them milliseconds.

If integration adds defensive lifecycle wrappers, exact sites are `5A72: D8 EC 41 F0` (release pointer `ED:EE`, RETURN continuation `5A76`) and `5A00: 6B EF 4F F0` (hold pointer `1E7:1E8`, original tail GOTO `9ED6`). Such guards need an owned-press latch and must not blanket-block these slots in other native UI modes. A bit4-suppressed release never reaches `5A72`, so any ownership latch must also clear after the native slot reaches history0/flags08. Do not clear it on the first raw zero sample. A core domain-change cancellation does not release suppression before physical release cleanup.

The normal event machine proves this `0x30` method. This review does not claim an exhaustive audit of every external flag writer or non-normal UI transition.

## Delta path and the original idle timer

`86D6` accepts W signed `±1/±10`, tail-entered by short paths `87CA/87DC` and timed paths `6DE6/6DFE`. The native body calls pointer `069`; MAN then executes `8716 MOVF EA,W;8718 ADDWF61,F`. Background service `63BC` consumes this accumulated native relative command and can transmit it later. A handled core edit must therefore bypass the entire original body, not merely replace its direct callback.

Because that native accumulation/transmit path also rearms the display-idle deadline, accepted core edits must retain timer rearming explicitly: `MOVLB0;CALL4A8E;CALLA174;CALL5D30`. `4A8E` loads C6:C7=`05DC`; `A174` produces the native timer representation; `5D30/5D34` stores it in AD:AE. Keep AD:AE updates when restoring scratch. This reuses the native deadline; it does not create a second timebase. Do not assume `05DC` means milliseconds.

## Exact native idle expiry, including its MAN-only gate

Normal UI calls `7F7E` from `6E5E`, itself called at `58D0`. The decisive chain is:

`7FA0/7FA4 load config7E:7F` → `7FA8 DECF POSTINC2,W;7FAA BNZ7FCC` → `7FAC CALL87B2` (22:23=`00AD`) → `7FB0 CALL732C` → `7FB4 IORLW0;7FB6 BZ7FCC` → `7FB8/7FBA/7FBC CLRF36/37/38` → **`7FBE CALL6C24`** → `7FC2..7FC8 CALLAA38` disarms AD:AE.

The mode test permits only native mode1 (MAN). Hook `7FBE` is the precise original MAN idle-expired callsite. RAM061 clearing is not an expiry event; native TX and mode change also clear it. Global `6C24` is not an expiry entry either: ordinary redraw calls it at `9A6E` and `9ABA`.

**TTL DEF/AIR1 limitation:** a `7FBE` hook alone cannot hide relative values while native mode is TTL. A bounded extension can use `7F9C:01 EC 38 F0` (`CALL7002`, continuation `7FA0`): call original7002, preserve its return context, and for native mode0 use the same `87B2 -> 732C` check of AD:AE; on expiry call core idle and disarm through `AA38`. MAN remains with the original `7FBE` path. This is a design candidate requiring wrapper replay validation, not a newly discovered native TTL expiry callback.

## Service and final LCD rendering

Leave `58D8 CALL5036` scan and `58DC CALL9DF4` single-slot consumption unchanged. Wrap `58E0 CALL75AC` by calling original75AC first, preserving its post-return state, calling core service, restoring, and RETURN `58E4`. This places canonical reconciliation after the current native event and native mode/camera processing.

Rendering there can provide immediate output, but does not guarantee final LCD contents. `58EA CALL732C` tests A9; on expiry `58F2 CALLA7C2`. That routine clears UI082 at `A7C4`, changes AD:AE at `A7CA/A7CE`, then `A7D2 GOTO9A48`. `9A4A..9A60` changes LCD bytes8A/90/92/93 and `9A6E CALL6C24` redraws the rows. This is after service58E0 and before the dirty comparison.

The minimal final overlay point is `5912 CALL859A`. Save the entry context, especially the prepared arguments1E..22; if UI082==0 and core magicA8, redraw; restore; tail GOTO original859A. `5900..5910` sets comparison of 11 bytes8A..94 with2C4..2CE, `5916/5918` checks the result and `591C CALLAB8C` marks dirty. Redrawing before that comparison lets native dirty tracking detect changes naturally. Keep `5938 CALL9D54` transport intact; its pointer B9:BA is prepared as008A at5932..5936.

## Native context to preserve

The shared ABI allows core/backend clobbers. For the reviewed helper set, a conservative outer frame is 109 bytes:

| Contents | Bytes | Why |
|---|---:|---|
| WREG, STATUS, BSR; FSR0/1/2; PRODL/H; TABLAT; TBLPTR L/H/U; PCLATH/U | 17 | Core/native helpers and indirect trampolines may clobber these |
| RAM01E..023 | 6 | Compiled arguments/results; includes LCD comparison arguments |
| RAM0B7..0FF | 73 | Bank0 locals and parameters including F2:F3, EA, B9:BA, C1..D0 |
| RAM1E5..1F0 | 12 | Active keyboard stack locals; consumer reuses pointer1E9:1EA after callbacks |
| RAM2C3 | 1 | Live outer5806 state read at593E/5940; alternatively prove each helper leaves it untouched |

Provider offsets C0..12C fit inside ABI B0..17F; existing backend bridge B0..B2 remains separate. This arithmetic does not prove physical SRAM capacity or non-overlap. Save W/STATUS before comparisons, and FSRs before using them to copy. Restore BSR and flags correctly. Do not restore intentional persistent changes such as config199/FEC19D..19F, selector/callbacks060/063..06E, Head02C/Model03F, LCD8A..94, queue state, AD:AE or owned slot flags.

Do not borrow IRQ save cells1A..1D: IRQ4108 saves FSR1/2 there and restores at4164..4170 before RETFIE1. Do not change interrupt settings, and do not snapshot/restore asynchronously published state as ordinary scratch. Complete ISR/helper concurrency proof is separate integration work.

Preserve hardware-stack structure through balanced CALL/RETURN and native PUSH/TOS trampolines; do not restore STKPTR/TOS as normal registers. The current selected native helpers should not reenter these hooks; a single save frame requires the actual wrapper/helper callgraph to establish that property. New helper calls require another clobber/nesting audit.

## Required integration evidence

Validate actual emitted wrappers against these preimages and continuations; replay handled, refused and fallback paths with sentinel registers/native scratch and asserted stack depth. Exercise C/MODEL/HEAD press/hold/release, mode/UI cancellation, original MAN idle, added TTL idle and A9 UI-timeout redraw. Prove physical RAM and native concurrency separately. No flashable package follows from this static contract alone.
