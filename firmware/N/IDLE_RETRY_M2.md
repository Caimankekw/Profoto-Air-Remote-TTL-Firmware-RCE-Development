# Nikon C5: retry a deferred AIR1 expiry

[中文](IDLE_RETRY_M2.zh-CN.md)

Developer: Caimankekw. New code is licensed under AGPL-3.0-only.

In M1, the native `7B52 → 7B72 → 7B76..7B7C` path called `A8C0` to clear deadline `B4:B5` even when a pending transaction prevented the AIR1 clear. Relative numbers remained visible, with no armed deadline to retry them. Both MAN and TTL DEF counterexamples were reproduced in the frozen M1 image.

M2 replaces the CALL at `7B72` with an equal-width GOTO wrapper. Initialized AIR1 with visible relative numbers calls shared `idle_expired` directly; that routine freshly samples native input and radio readiness. A zero result restores context and continues at `7B80`, retaining the native expired state. Success continues at `7B76`, which executes the original timer disarm. A2, uninitialized operation, and no-visible-number cases retain the original consume path. Original expiry arithmetic, deadline values, key-driven rearming, and HSS paths are unchanged.

Run from the source package root:

```powershell
python -X utf8 -B N/test_idle_retry_m2.py
python -X utf8 -B -O N/test_idle_retry_m2.py --report N/idle_retry_m2_results_optimized.json
```

Both modes pass 23 cases: MAN/TTL DEF; pending transaction, native busy, camera busy, and radio queue busy; ordinary and wrapped deadlines; retry after readiness; exact deadline boundary; inactive timer; transition to A2; and TTL ABC/FEC negatives. Checks execute the native entry, require the original disarm after success and its absence after rejection, and verify an empty return stack. No native or shared function is replaced by a success stub. These commands generate the reports.

Optionally add `--baseline-directory <original-M1-build/N-directory>` to reproduce the old defect. This is an external optional input, not a source-package dependency. The directory must contain M1 `profile.json`, `linked_components.json`, and exactly one `.partial.bin`.

Evidence boundary: bounded machine-code replay with explicit peripheral inputs; no physical clock, asynchronous interrupt, or radio reception simulation. It does not establish hardware boot or exposure behavior.
