# Fujifilm AIR2-P8-M2 UI fixes

[简体中文](M2_UI_FIX.zh-CN.md)

Developer: Caimankekw. New code is licensed AGPL-3.0-only. This document covers offline machine-code replay, not hardware boot, display or radio validation.

## Changes

1. **Relative values now expire on the TTL DEF page when AIR1 is selected.** The stock F A5 gate at `0x8618..0x8622` admitted only MAN into the A6 timer check. M1's expiry hook at `0x8636` was consequently unreachable from TTL DEF. M2 adds a guarded entry at `0x8618`, requiring initialized state, the expected native object, and TTL + DEF + AIR1 before extending admission. MAN, TTL ABC and AIR2 retain their respective behavior. The original activity path sets the deadline and stock `0x8FBE/0x78E0` checks it; there is no parallel timer.
2. **ALL lights all three selection boxes on the visible page.** F's native `0x880E` helper handles selectors 1/2/3 but clears every box for selector 7. M2 overlays the union of F's own `LCD87` box bits, `0x02 | 0x08 | 0x20`, after that helper. Individual rows and ABC/DEF labels retain F's native layout. No camera ABC mask or transmitted command is changed by rendering.
3. **A pending AIR1 transaction no longer consumes the only opportunity to clear expired values.** Stock `0x78E0` latches A6 to `0xFFFF` on expiry; the completion path at `0x863A..0x8640` then disarms A6 with zero. M1 ran that completion even when the shared core refused the clear because a transaction was pending. M2 uses a GOTO splice at `0x8636`: an unsuccessful AIR1 clear retains the `0xFFFF` expired latch and retries after the transaction drains, then runs the stock completion. The shared core resamples native edit and radio admission before clearing; busy camera, queue or checked pending-interrupt gates also defer to this retry path. AIR2 remains visible and consumes its native expiry normally rather than retrying forever.

## Validation

From the source root, run `python -X utf8 -B F/test_ui_parity_m2.py --out <report.json>`. In the development workspace, that root is `analysis/air_remote_ttl_multi_air2`. The test builds machine code in memory with the production linker and never runs an installer.

All 102 cases pass with ordinary Python and with `-O`:

| Coverage | Cases |
|---|---:|
| Native press and power entries, followed by the actual `0x8618` TTL/MAN × AIR1/AIR2 × ABC/DEF × row/ALL expiry path | 32 |
| Actual `0x742E` display entry and native LCD bits over the same combinations | 32 |
| Pending AIR1 expiry, transaction drain and clear retry, including the 15-bit tick wrap | 6 |
| Pending AIR2 consumes its normal native expiry | 2 |
| A stale idle snapshot followed by native camera/queue/IRQ busy gates: no redraw, then retry after release | 27 |
| Uninitialized-state fallback retains the stock mode gate | 2 |
| All changed stock bytes lie within declared AIR2 hooks and generated sections | 1 |

The seven existing F integration cases also pass. Each idle replay checks that ISR-owned `0xFE/0x2B1/0x1DA/0x1E0` remain intact. Expiry leaves absolute targets, TTL compensation, group masks and transmitted frames unchanged. Explicit MMIO, NVM-controller and downstream queue-consumption fixtures are used. This does not measure physical timing, radio completion or actual LCD visibility.

The script generates its JSON report. Development-workspace records are `m2_verification/ui_parity_results.json` and `m2_verification/ui_parity_results_optimized.json`; these historical generated files are not required in the source archive. Subsequent shared-core integration can change the full-image hash; packaging must rerun this test against the final linked image. Stock HSS, Canon firmware and frozen M1 releases are unchanged. Qualification metadata is updated by final integration.
