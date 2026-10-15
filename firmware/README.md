# Air Remote TTL N/S/F/O · AIR2-P8-M2

English | [简体中文](README.zh-CN.md)

Developer: **Caimankekw** · Authored code: **AGPL-3.0-only**

**M2 fixes issues found against Canon P8; all four final images passed bounded offline regression and HSS-preservation checks.** Hardware startup and operation have not been validated for the four ports. The targets are separate Air Remote TTL variants:

| Model tag | Device | Stock input revision |
|---|---|---|
| N | Air Remote TTL-N, Nikon | C5 |
| S | Air Remote TTL-S, Sony | A6 |
| F | Air Remote TTL-F, Fujifilm | A5 |
| O | Air Remote TTL-O, Olympus | A4 |

Each model requires its own reviewed image and portable ZIP. Never substitute another mount's updater. These are experimental modifications, not an official release, affiliation or endorsement. Read [DISCLAIMER](DISCLAIMER.md), [LICENSE](LICENSE) and [NOTICE](NOTICE.md).

## Implemented behavior

The AIR2 control policy follows Canon AIR2-P8: MAN AIR1 relative adjustment, MAN AIR2 absolute targets, six groups on ABC/DEF pages, C+HEAD paging, and C+MODEL switching AIR1/AIR2 in MAN. TTL consumes C+MODEL without changing the remembered manual subtype. A/B/plus/minus do not enter the secondary chord window. AIR1 values appear temporarily after successful edits; enabled AIR2 targets stay visible. Offline replay covers these paths; physical controls and lights remain part of hardware acceptance.

TTL ABC uses exposure compensation; DEF remains manual using the remembered AIR1/AIR2 subtype. This is **not six-group automatic TTL**. Mixed ALL adjusts ABC FEC and DEF manual values together. An absolute DEF update can refresh ABC manual-target caches through the complete six-slot command. Camera exposure and the first TTL shot after such an edit need separate checks.

**Each model retains its own original HSS/camera/RF scheduling implementation.** Canon HSS-P3 modifications are not linked into these ports. The extension submits 16-byte command bodies to the existing native queue and scheduler; it does not replace the UART sender or force a new transmission rate. Queue admission is not acknowledgment from a light. When the queue is full, a pending frame stays pending; later edits can be refused while a transaction is active. No arbitrary-rate key response or Connect Pro performance equivalence is promised.

**Settings persistence is enabled in all four versions.** The model-tagged V5 record stores the effective TTL/MAN-AIR1/MAN-AIR2 mode, last manual subtype, page, six AIR2 targets and Head/Model states. Its separate pages at `0xF800`/`0xFC00` preserve the original journal; it does not import Canon V1–V4 or another mount's records. Save/reload paths passed bounded offline replay, while actual power-loss behavior remains untested. Loading settings does not itself synchronize lights. Storage ranges, RAM, hooks, calling conventions, display and clock units were handled per model; Canon addresses are not defaults.

The four ports retain a separate storage-failure policy: after an erase, write or readback failure, further saves are disabled for that power cycle and retried after reboot. Canon P8 retains dirty state and retries later. This is separate from the startup mask fix and does not mean earlier edits were saved. Native asynchronous queue timing also differs from Canon synchronous sending; rapid physical key response still requires hardware tests.

## M2 fixes

- All four models: retain saved ABC Head/Model states when native mode changes during deferred startup restoration, preventing defaults from replacing and persisting over them.
- All four models: retain the AIR1 expiry condition when native work is busy, then retry display clearing when idle instead of leaving temporary values permanently visible.
- Fujifilm: cover TTL/DEF/AIR1 expiry from the real native idle entry; illuminate all three selection boxes for ALL.
- Sony: call the actual page-letter hint from C+HEAD paging, then restore the current page power display.

If M1 has already persisted incorrect switch states, M2 cannot infer the overwritten values. Check and reset the six Head/Model states after upgrading. Valid same-model V5 records retain the same field layout.

The reference is the frozen Canon AIR2-P8 image reported hardware-tested by the user. This tree does not modify that Canon release. The comparison also found the similar Canon AIR1 busy-at-expiry issue, handled in the separate AIR2-P8-FIX1 correction branch. FIX1 still requires hardware acceptance and cannot inherit the original P8 result. Matching normal RF frames does not replace startup, UI or all busy-state verification.

## Development evidence

`shared/NATIVE_BACKEND_ABI.md` defines the core/native interface. `shared/stock_inventory.json` identifies exact stock EXEs and records stock-only decoding checks; it is not evidence that an AIR2 port is complete. Model directories contain their own analysis and tests. A model must pass final-image checks for the core, native adapter, integration, HSS preservation and storage backend before packaging. Offline checks do not replace startup, RF, exposure, long-term or power-loss tests.

M2 adds regression coverage for startup mask restoration, the real native idle route, ALL selection boxes and page hints. Package gates must bind the final images, not reuse passing M1 reports. Ordinary Python and `python -O` runs check that critical checks survive disabled assertions. The source archive must also rebuild EXE/HEX/partial images byte-for-byte in an independent directory. Normal and `-O` runs each pass 312 integration cases, 96 boot-restoration cases and 226 model-specific regression cases. All 1,024 normal radio cases match, as do 26 normal multiaction traces (178 steps) per model. Twelve scheduling-boundary traces document retained admission differences from Canon. Exact counts and hashes are in the [validation summary](shared/final_validation_m2.json) and corresponding release reports. These checks do not establish RF delivery, hardware HSS timing or universal camera compatibility.

No firmware, updater, USB command or GitHub publishing action is run by the portable packager. It uses only already reviewed results. This tree does not create a remote repository or upload a release.

## Rebuild from the corresponding source archive

Use Python 3.9 or later with its standard library. Extract `source.zip` and run commands from its top-level directory. No Canon project, Canon firmware, APK, account session or original developer workspace is required. The included 73,725-byte `shared/reference/c11_offset_transform.bin` is a hash-pinned, derived byte-transform parameter table, **not a vendor firmware image**.

Supply the original, unmodified EXEs yourself in the following layout; they are deliberately excluded from the source archive. Keep their original `license_3rd_party.txt` alongside each EXE when preparing portable packages.

```text
inputs/air_remote_ttl/
  air-remote-ttl-n-firmware-c5-win/Air-Remote-TTL-N-Firmware-C5.exe
  air-remote-ttl-s-firmware-a6-win/Air-Remote-TTL-S-Firmware-A6.exe
  air-remote-ttl-f-firmware-a5-win/Air-Remote-TTL-F-Firmware-A5.exe
  air-remote-ttl-o-firmware-a4-win/Air-Remote-TTL-O-Firmware-A4.exe
```

The original EXE hashes are pinned in `shared/stock_inventory.json` and checked in code. First regenerate the local stock HEX, partial image and known-byte mask with `inspect_variants.py`; these generated vendor files are analysis/build inputs, not source-archive members. Then build **one model per Python process**:

```powershell
$firmwareRoot = (Resolve-Path '.\inputs\air_remote_ttl').Path
python -B shared\inspect_variants.py --firmware-root $firmwareRoot
if ($LASTEXITCODE -ne 0) { throw 'Stock inspection failed' }
$variants = @{ N='C5'; S='A6'; F='A5'; O='A4' }
foreach ($tag in 'N','S','F','O') {
  $revision = $variants[$tag]
  $folder = 'air-remote-ttl-' + $tag.ToLower() + '-firmware-' + $revision.ToLower() + '-win'
  $original = Join-Path (Join-Path $firmwareRoot $folder) ('Air-Remote-TTL-' + $tag + '-Firmware-' + $revision + '.exe')
  python -B shared\build_variants.py --model $tag --profile "$tag\port_profile.json" --source $original --output "build\$tag"
  if ($LASTEXITCODE -ne 0) { throw ('Build or replay failed: ' + $tag) }
}
```

For one model, add `--model N` to the inspection command and run only that model's build. Always pass `--firmware-root` and `--source` explicitly; default paths also support the original development workspace. The builder requires a reviewed `offline_qualification_complete` profile, every required validation gate, and passing final linked-machine-code replay with no pending coverage. A candidate profile without final qualification is rejected; do not bypass these gates to produce a package.

The custom EXE must reproduce byte-for-byte for the same source snapshot, profile and pinned original EXE. Rebuilt verification JSON may contain different local paths/source-inventory hashes and need not be byte-identical. The emitted `.hex` and `.partial.bin` remain developer outputs; do not flash them independently. `tools/package_source.py --check` checks the explicit source inventory and ZIP structure in memory. Only an explicit `--output NEW.zip` writes a source archive after the source set is frozen.

The archive includes the actual shared and nested model dependencies, bounded final-image tests and focused ABI evidence. Historical matching scripts, full parity_review captures, large temporary analyses, candidate dumps/listings and old standalone PASS reports are omitted; it does not promise to rerun every exploratory analysis. Sony/Fuji use package-local assembler support; their inclusion does not import Canon HSS policy.

New regression scripts read stock EXEs from the source root's `inputs/air_remote_ttl/` layout by default. A present but incorrect local file must fail fingerprint validation rather than fall back to another input. Complete stock-input inspection above first. `shared/test_boot_restore_m2.py` and the model-specific M2 idle/UI regressions can then run in this independent source directory.

## Portable package contract

`tools/package_portable.py` accepts a model's custom EXE, its hash-pinned original EXE, patch plan, repacker report, final readiness record and matching source ZIP. It rejects stock-only/candidate inputs, incomplete checks, another model, changed documents/source, undeclared wire edits and existing output paths. Use `--check` for in-memory preparation; explicit `--export` creates a new directory and ZIP.

Each package contains the selected custom GUI, that model's unmodified factory recovery GUI, English/Chinese instructions and disclaimers, license notices, corresponding source ZIP, compact evidence and SHA256 checksums. It contains no bare BIN/HEX, device captures, unrelated model firmware or NSIS wrapper. The source ZIP must include the required common dependencies; the current development tree is not by itself proof of a standalone source build.

The original `license_3rd_party.txt` is required and copied unchanged. It is read beside the original EXE, or supplied explicitly with `--third-party-notices`; its known hash is checked. The source ZIP has one top-level directory and a `source_manifest.json` listing every other file with `size` and `sha256`. Required binary reference inputs must be individually declared in readiness; executable outputs and private capture/account files are excluded.

The readiness format is `multi-air2-portable-readiness-v1`; its status must be `OFFLINE_VALIDATED_EXPERIMENTAL`. It binds model/release, EXE/stock/plan/repacker/source hashes, packager and all seven root documents, plus final-image-bound passing reports covering `core`, `native_adapter`, `integration`, `hss_preservation` and `persistence_backend`. `nv_enabled` must agree with the persistence report. A disabled, explicitly documented backend may pass its disabled-path checks without claiming saving works. `export_authorized` is an internal reviewed-build gate, not a hardware test.

```powershell
python tools/package_portable.py --model N `
  --updater "N\build\Air-Remote-TTL-N-AIR2-P8-M2.exe" `
  --original "inputs\Air-Remote-TTL-N-Firmware-C5.exe" `
  --plan "N\build\patch_plan.json" `
  --repack-report "N\build\verification.json" `
  --readiness "N\build\portable_readiness.json" `
  --source-archive "inputs\AIR2-P8-M2-source.zip" `
  --output "release\N-AIR2-P8-M2" --check
```

After the final review, replace `--check` with `--export`. This example describes the interface and does not assert those candidate files already exist. See the script's `--schema` output for the exact readiness fields.

## Hardware acceptance after a validated package exists

Extract the complete matching-model ZIP and read its model-specific `PACKAGE.md`. Open the custom EXE through its original GUI, follow its device identification prompts and manually initiate updating. The package does not automatically back up or flash a device. Preserve the original recovery GUI; including it does not guarantee recovery.

Check normal battery startup and buttons first, then paging/mode changes, five individual ±0.1 edits away from limits, actual light targets, Head/Model states, ABC FEC versus DEF manual behavior, six-group triggering, original HSS and TTL exposure. Check persistence only when the package says it is enabled; test save/reboot and first exposure separately. Fixed hashes and success dialogs are not evidence that all these behaviors passed.
