# Air Remote TTL-F · Fujifilm AIR2-P8-M2

English | [简体中文](README.zh-CN.md)

Developer: **[Caimankekw](https://github.com/Caimankekw)** · Authored work: [AGPL-3.0-only](LICENSE)

Experimental AIR2 firmware for **Fujifilm Air Remote TTL-F, stock A5 only**. This is the [fujifilm-air2-m2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-air2-m2) development branch; unmodified-firmware analysis is on [fujifilm-a5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-a5). [Release fujifilm-air2-m2-20261016](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/fujifilm-air2-m2-20261016) provides Windows packages and exact corresponding source.

**Hardware boot, camera/radio behavior and power-loss handling have not been confirmed for this port.** Offline checks and Canon hardware experience do not establish these results. This release preserves the existing M2 firmware bytes and adds model-specific publication/build/package entry points. It retains this model's original HSS, not Canon HSS-P3.

## Controls and changes

- MAN AIR1: relative control; values appear temporarily after editing.
- MAN AIR2: absolute targets; enabled groups on the current page remain visible.
- C + HEAD switches ABC/DEF pages. In MAN, C + MODEL switches AIR1/AIR2; TTL ignores this chord without changing the remembered manual type.
- A, B, plus and minus use normal key paths. Busy transactions can still reject edits; no arbitrary tap-rate guarantee is made.
- MODE returns to the remembered manual type. Six AIR2 targets, Head/Model switches, mode and page are persisted.
- ALL affects six groups. **TTL ABC is exposure compensation; DEF uses the remembered manual type, not automatic TTL.** Displayed AIR2 values are requests, not feedback from lights.

M2 preserves saved switch masks across startup mode changes, retries AIR1 display expiry after busy periods, fixes Fujifilm TTL/DEF expiry and ALL boxes, and restores Sony page hints/release redraw. Only the relevant model paths execute. If M1 already stored incorrect switch values, check and reset all Head/Model switches after upgrading. Persistence stops retrying after a write/readback failure for that power cycle; this differs from Canon's dirty-state retry policy. See [full behavior and limits](firmware/README.md).

## Build and layout

Use Python 3.9+ and the unmodified `Air-Remote-TTL-F-Firmware-A5.exe`. No previous workspace or Canon EXE is required.

```powershell
python -B build.py --original "C:\firmware\Air-Remote-TTL-F-Firmware-A5.exe" --output "build\M2"
python -B tools/package_source.py --out "artifacts"
```

Output paths must be new. The root builder binds this branch to TTL-F, verifies input/source fingerprints, retains its isolated staging tree and executes source generators in a fresh process. It does not run an updater or access USB. Root [release_profile.json](release_profile.json) pins the frozen firmware and expected result; [model.json](model.json) pins the stock input.

| Path | Contents |
| --- | --- |
| `reverse/`, `tools/inspect_original.py`, `tools/reference/` | Original-only evidence and read-only extraction |
| `firmware/` | Complete frozen 125-file M2 dependency/test closure for reproducibility |
| `build.py`, `tools/package_source.py` | Model-bound entry point and corresponding-source archive |
| `windows/` | Windows self-extracting and portable package build source |
| `tests/` | Publication/build checks |

The shared firmware snapshot includes the other model adapters because verification and packaging share their profiles. The branch root builds only TTL-F; other-model binaries are not included. Inner documentation describes the historical frozen M2 source package; the root documentation describes this publication's additional Windows wrapper. Generic transform reference bytes are not a vendor firmware image. Full vendor EXE/HEX/BIN and device captures are excluded from source.

| Fixed output | SHA-256 |
| --- | --- |
| Custom GUI updater | `ac0fbd824a6fa23c754b352e7293caa2675500d6921188153c012272cdc0e3de` |
| Partial analysis image | `edf60a81b787b0548f481133f899fc3f58b7f5a1ce4d5194cb90826600e6e1e5` |

The first two plaintext bytes remain unknown. **Do not flash a partial BIN.** Use the matching GUI updater. The original GUI/loader container is retained; resource modification may invalidate its vendor signature.

## Windows release and validation

The self-extracting EXE and portable ZIP include the modified GUI updater, matching unmodified stock recovery GUI, corresponding source, bilingual instructions/disclaimers, AGPL text and third-party notices. Extraction does not flash firmware. Updating requires manual action in the GUI. Recovery is not guaranteed. See [Windows packaging](windows/README.md).

The frozen M2 validation records 78 integrated cases, 24 startup restoration cases and 102 model-specific cases for this model, under normal and optimized Python. Cross-model evidence contains 1,024 normal radio-frame matches and 26 operation traces / 178 steps per model compared with Canon. Busy admission differs; these are bounded software checks. Existing independent archive rebuilds reproduced EXE/HEX/partial image exactly. This publication also rebuilds each branch archive and statically verifies its packages; release verification records the result. No installer/updater or hardware is executed in packaging.

Read [DISCLAIMER](DISCLAIMER.md), [NOTICE](NOTICE.md), [LICENSE](LICENSE) and [CHANGELOG](CHANGELOG.md). AGPL covers authored work; vendor firmware and mixed binaries retain their respective terms.

## macOS packages

Native Mac packaging instructions and build source are in [macos/README.md](macos/README.md). The Mac package retains the vendor GUI and USB helper, embeds the exact existing Windows firmware HEX, and rebuilds the outer application seal with an ad-hoc signature before creating an APFS/UDZO DMG. It has no vendor Developer ID signature or Apple notarization. The GUI is Intel x86_64; Apple Silicon requires Rosetta. Hardware flashing has not been verified on macOS.

Mac packaging source is identified by `fujifilm-air2-m2-20261016-mac`; the original firmware release tag and Windows attachments remain unchanged. The new Mac source archive includes the complete firmware and packaging sources. See the dedicated Mac instructions and verification assets in the existing release.
