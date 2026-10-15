# Olympus A4: retry a deferred AIR1 expiry

[中文](IDLE_RETRY_M2.zh-CN.md)

Developer: Caimankekw. New code is licensed under AGPL-3.0-only.

In M1, both the native MAN path `7FA0 → 7FBE → 7FC2..7FC8` and the TTL DEF service wrapper called `AA38` to clear deadline `AD:AE` even when a pending transaction prevented the AIR1 clear. Relative numbers remained visible without a deadline to retry them. Both counterexamples were reproduced in the frozen M1 image.

M2 replaces the CALL at `7FBE` with an equal-width GOTO wrapper, preserving exactly one call to original `6C24`. Initialized AIR1 with visible relative numbers directly calls shared `idle_expired`, which freshly samples native input and radio readiness. A zero result restores context and continues at `7FCC`, retaining the native expired state. Success continues at `7FC2` for original timer disarm. Original consume paths such as A2 remain intact. TTL DEF service likewise calls `AA38` only after a successful shared clear. Original expiry arithmetic, deadline values, key-driven rearming, and HSS paths are unchanged.

Run from the source package root:

```powershell
python -X utf8 -B O/test_idle_retry_m2.py
python -X utf8 -B -O O/test_idle_retry_m2.py --report O/idle_retry_m2_results_optimized.json
```

Both modes pass 23 cases: MAN/TTL DEF; pending transaction, native busy, camera busy, and radio queue busy; ordinary and wrapped deadlines; retry after readiness; exact deadline boundary; inactive timer; transition to A2; and TTL ABC/FEC negatives. MAN starts at `7FA0`. TTL DEF executes the real service wrapper including original `75AC`, with a native camera-busy input holding its pending transaction. Checks require the original disarm after success and its absence after rejection, and an empty return stack. No native or shared helper is replaced by a success stub. These commands generate the reports.

Optionally add `--baseline-directory <original-M1-build/O-directory>` to reproduce the old defect. This is an external optional input, not a source-package dependency. The directory must contain M1 `profile.json`, `linked_components.json`, and exactly one `.partial.bin`.

Evidence boundary: bounded machine-code replay with explicit peripheral inputs; no physical clock, asynchronous interrupt, or radio reception simulation. It does not establish hardware boot or exposure behavior.
