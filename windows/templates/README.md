# Air Remote TTL-@MODEL@ AIR2-P8-M2 Windows package

[简体中文](README.zh-CN.md) · Developer: **Caimankekw** · **@RELEASE_DATE@** · `@TAG@`

This experimental firmware is only for **Air Remote TTL-@MODEL@ (@BRAND@)**. It is not an official Profoto release. Read [DISCLAIMER](DISCLAIMER.md), [LICENSE](LICENSE) and [NOTICE](NOTICE.md). Authored custom code is AGPL-3.0-only; vendor firmware, updater and third-party materials retain their own terms. Vendor notices are included in `license_3rd_party.txt`.

**This model's M2 image has not been booted or camera-tested on hardware.** Offline radio, display, persistence and HSS preservation checks do not establish hardware acceptance. Canon P8 hardware results do not validate this model. The target's original **@STOCK_REVISION@ HSS remains unchanged**; Canon HSS-P3 is not imported.

Source: [release snapshot](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/@TAG@) · [development branch](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/@BRANCH@). The exact corresponding source is included as `source.zip`; `package_manifest.json` records its SHA256 and its internal `source_manifest.json` inventories every source file.

## Use

1. Run the setup EXE, choose English or Simplified Chinese, read the disclaimer/license and choose a new destination folder. The default is `%LOCALAPPDATA%\Caimankekw\AirRemote-TTL-@MODEL@\AIR2-P8-M2`. The wrapper only extracts files; it does not install drivers, access USB or flash devices.
2. Opening the updater at the end is optional and **unchecked by default**. Alternatively, open `@UPDATER_NAME@` from the extracted folder. Extract the entire portable ZIP before using it.
3. Connect only the intended Air Remote TTL-@MODEL@, follow the original GUI, check the detected model and manually start its update. Keep the connection until it finishes.
4. Disconnect USB and start normally on batteries. Check the display, menus and buttons before camera tests. If `EC!` occurs and the original updater still communicates, `restore_original/Air-Remote-TTL-@MODEL@-Firmware-@STOCK_REVISION@.exe` can be used to attempt recovery. Recovery is not guaranteed.

The vendor container outside the firmware resource is unchanged. The modified updater does not have a valid original signature; the outer wrapper is unsigned. No alternate command-line flasher is included. The outer wrapper uses normal user privileges; the original updater's own requirements remain applicable.

## AIR2 controls and limits

- **C + HEAD:** switch ABC/DEF pages in TTL and MAN.
- **C + MODEL:** switch AIR1/AIR2 in MAN. TTL consumes this chord without changing the remembered manual subtype. These chords do not also toggle Head/Model.
- AIR2 displays all enabled groups' absolute power targets. AIR1 retains temporary relative values. TTL ABC is exposure compensation; DEF uses the remembered manual AIR1/AIR2 subtype, **not automatic TTL for six groups**.
- ALL applies to six groups. AIR2 power and Head/Model states persist; the last MAN subtype is restored. Check the actual lamp behavior as well as the remote display.
- A/B/plus/minus have no added chord wait. Native scanning and busy radio transactions still limit acceptance; busy adjustments can be rejected instead of queued. Do not assume identical tap acceptance or busy timing to Canon.

M2 fixes delayed-boot restoration of saved Head/Model masks and AIR1 expiry during busy transactions, with additional model-specific display fixes documented in [CHANGELOG](CHANGELOG.md). A state already incorrectly saved by M1 cannot be reconstructed: after upgrading, check and set Head/Model switches deliberately. A detected NVM save failure is latched for the current power cycle; persistence must be tested separately.

## Files and verification

The package contains the frozen M2 updater, matching original recovery updater, exact corresponding source, bilingual documents, licenses and manifests. Packaging leaves the runtime firmware unchanged.

- M2 updater SHA256: `@UPDATER_SHA256@`
- Expected partial firmware image SHA256: `@IMAGE_SHA256@`

The partial BIN is a research/build artifact, **not a directly flashable file**. Packaging verifies complete updater pins, source inventory, portable ZIP contents, PE metadata and every statically extracted NSIS payload file. It never executes the delivered updater/installer. Check the release's `package_verification.json` and `SHA256SUMS.txt`.

Python is not required to use the delivered GUI. To reproduce the wrapper, unpack `source.zip` and follow `windows/README.md`. Unmodified NSIS 3.13 components retain their license in `NSIS-COPYING.txt`; [NSIS source](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/) is available separately.
