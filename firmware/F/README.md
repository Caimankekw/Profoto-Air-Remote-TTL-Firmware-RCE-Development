# Air Remote TTL-F A5: AIR2 adaptation evidence

This directory contains offline development source and evidence; the shared release process emits installers separately. The baseline is the original Fujifilm A5 program. Canon HSS-P3 is not linked, and the native Fujifilm HSS and camera handlers are unchanged. See [M2 UI fixes](M2_UI_FIX.md) for expiry, ALL selection boxes and busy-state retry changes.

The object-based PIC18 ABI differs from Canon C11. F A5 has 12 four-byte input objects at `0x010A..0x0139`; C/MODEL/HEAD are `0x011E/0x0122/0x0126`, and +/- are `0x012A/0x012E`. Original scan/event code provides short and held steps without adding a chord delay to repeated power-key presses.

Native radio type `0xB2CE` returns 2, selecting RSGT1 and a 16-byte body. The bridge uses original enqueue `0xA60A`, keeping the original scheduler. The TX ring descriptor is `0x92`, its buffer is `0x500`, capacity 100; descriptor offsets are write/read/count/capacity/buffer-address. Admission accounts for one marker plus the entire 16-byte body. Original strict capacity checking admits count 82 and refuses 83 when asked for 17 bytes.

The original `0x7AD2` formatter can render 0.1 through 9.9 and the 10 endpoint. Absolute rendering uses its existing digits and clears the sign with the native sign helper. Native blank and Head OFF helpers are preserved.

Files:

- `F_A5_adapter_evidence.json` and `build_evidence.py`: confirmed addresses, native preimages and 14 static assertions.
- `native_backend.py`: parameterized snapshot, input, queue, native-state projection and LCD rendering. Transmission and NV admission require explicit profile proofs.
- `native_hooks.py`: eight bounded startup, service, key, power, LCD and native-expiry hooks, including the native mode-gate extension for TTL DEF AIR1; no HSS hooks.
- `test_native_backend.py` and `native_backend_test_report.json`: ten categories of instruction replay using actual A5 helpers, with no function stubs, including stale-mode projection refusal before mutation.
- `test_integrated_hooks.py` and its report: seven stock/core/backend/hook integration cases, including native power and group entries, real queue output, nonrecursive display, expiry and DEF isolation. It creates no HEX or EXE.
- `test_ui_parity_m2.py`: 102 M2 integration cases through the actual upstream idle and LCD entries, covering mode combinations, ALL, timer wrap and busy-state retry. Use `--out` to generate a JSON report.
- `audit_clock_irq.py` and its evidence: IRQ control flow, native tick, radio inhibition, wake latch, ISR writes and NVM-register analysis.
- `port_profile.json`: explicit F A5 mappings, state allocation, native clock domain, admission and persistence proofs, geometry and protected original ranges. Final qualification is bound by the shared full-image builder.
- `c11_codec_candidate.listing.txt`: a linear candidate listing; embedded data can also decode as instructions.
- Alignment/candidate JSON files: exploratory suggestions only, never authoritative patch addresses.

Run the Python test scripts from the workspace root with `python -X utf8 -B`.

Hook/context preservation, native-mode callbacks, six-group rendering and ABC/DEF state isolation have been replayed. Shared bounded RAM and hardware audits support `0x680..0x7FF` under normal-object/legal-index assumptions. The original `0x600..0x67F` remains untouched. This is not physical RAM validation.

The ISR publishes a camera command to RAM `0x0FE`; restoring the entire `B0..FF` range would lose that event. Context restoration excludes `0x0FE/0x2B1/0x1DA/0x1E0`. Page changes briefly display A/b/C or d/E/F until the next redraw; DEF hides the fixed ABC labels. Camera ABC masks always remain ABC.

Local `nv_load/nv_commit` exports are disabled placeholders for replacement by the shared verified persistence component. Final NV linking must supply actual `read_inputs` and hardware/RAM/page/ISR proofs. `native_nv_gate_proven=True` permits bit2 only when the original idle gates pass and all keys are released. The original ISR does not touch table or Flash-control registers; the shared backend must still restore the original interrupt-enable state. Full NV-enabled image replay and physical validation are recorded separately.

Optional admission code requires normal UI, camera state 1, no native pending work, an empty TX queue, and clear camera interrupt flags. An independent control-flow audit found no ISR producer for the TX ring; the ISR produces the separate RX ring. The bridge therefore leaves interrupts enabled. Admission cannot predict a future camera interrupt and is not an RF or lamp execution acknowledgement.

See [the Chinese version](README.zh-CN.md) for addresses and integration notes. Project licensing and experimental-firmware disclaimers apply; offline tests do not establish physical HSS performance or a validated installer.
