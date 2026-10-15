# Branch build and source checks

These checks cover the added publication wrappers. They do not replace the
frozen firmware's linked replay and do not access hardware.

```powershell
python -X utf8 -B tests/test_branch_tools.py
```

The 13 tests reject wrong model/release fingerprints, changed or incomplete
source, unsafe or duplicate archive paths, changed manifests and existing
outputs. One non-executable input fixture is retained under `build/tests/`.

`build.py` runs the selected model's stock inspection and linked replay in
separate Python processes, then compares the image and updater with the fixed
M2 SHA-256 values. The complete 125-file shared source closure remains intact;
this branch's `release_profile.json` locks the supported target. Only this
model's pinned original updater is needed for the documented build command.

Generated logs may contain local paths. Publish the sanitized
`build_verification.json`, not the complete scratch or artifacts directories.

The frozen `firmware/` tree also contains historic inspection helpers and
multi-model tests; not every exploratory script is a standalone build entry.
Use the documented root wrapper for a single-model rebuild.
