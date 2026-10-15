# Windows packaging source

[简体中文](README.zh-CN.md) · Developer: **Caimankekw** · Authored code: **AGPL-3.0-only**

This directory packages the branch's frozen **AIR2-P8-M2** updater as a bilingual NSIS extraction wizard and portable ZIP. It uses `../release_profile.json` and `../model.json` to lock the target, firmware/updater hashes and original recovery input. It does not modify runtime firmware or access USB. Each non-Canon target retains its stock HSS and has not yet been validated on hardware.

## Build

Python 3.9+ uses only the standard library. Obtain the original vendor updater and its adjacent `license_3rd_party.txt`, build the M2 updater with root `build.py`, then create the exact corresponding source ZIP with `tools/package_source.py`. The source tree must be final before making that ZIP.

Supply the complete unmodified NSIS 3.13 directory and 7-Zip 26.04 x64 `7z.exe` with adjacent `7z.dll`. `input_manifest.json` pins the complete NSIS tree, 7-Zip and vendor notice; the root profiles pin model-specific inputs. Tool paths are explicit and no downloads occur.

```powershell
python -B windows/test_build_package.py
python -B windows/build_package.py `
  --updater "C:\inputs\Air-Remote-TTL-N-AIR2-P8-M2.exe" `
  --original "C:\inputs\Air-Remote-TTL-N-Firmware-C5.exe" `
  --vendor-notice "C:\inputs\license_3rd_party.txt" `
  --source-archive "C:\inputs\model-source.zip" `
  --source-sha256 "REPLACE_WITH_SOURCE_ARCHIVE_SHA256" `
  --nsis-dir "C:\tools\nsis-3.13" `
  --seven-zip "C:\tools\7zip\7z.exe" `
  --output "C:\output\new-model-package"
```

The example names are Nikon. Use the model pinned by this branch: N/C5, S/A6, F/A5 or O/A4. The wrapper cannot select another model through CLI arguments. The output directory must not already exist. Inputs and older packages are never overwritten or deleted.

The source ZIP has one `<name_slug>_Source/` root and an `airremote-air2-branch-source-v1` manifest. The shared source parser checks its complete inventory and frozen firmware files; the wrapper also compares all archived `windows/` files, root legal documents and profiles with the current tree.

## Output and verification

Output includes a model-named `Custom-Updater.exe`, `Windows-portable.zip`, extracted payload, `package_verification.json`, checksums and compiler/extractor logs. The payload includes the frozen M2 GUI, matching stock recovery GUI, exact `source.zip`, bilingual instructions/legal documents/changelogs, original vendor notice, NSIS license and file manifests.

The wizard runs as the current user, refuses an occupied destination, and leaves opening the updater unchecked by default. It offers English/Chinese disclaimer and AGPL pages. It does not install drivers, silently update, delete files or add an uninstall flow. The original updater retains its own execution requirements.

Only the supplied compiler and archive extractor are executed during packaging. Checks verify the portable archive and every statically extracted NSIS file byte-for-byte, including expected NSIS components, and inspect PE product/developer identity and `asInvoker`. The installer and updater are never executed. Complete GUI hashes are pinned; the firmware-image hash records the expected prior build identity, not an additional independent device measurement. No byte-identical outer EXE reproducibility is claimed, and static checks do not replace Windows UI or hardware testing.

The original NSIS notice is preserved in `vendor/NSIS-COPYING.txt`. Authored packaging code follows the root LICENSE; vendor materials retain their original rights as detailed in the bilingual NOTICE and disclaimers.
