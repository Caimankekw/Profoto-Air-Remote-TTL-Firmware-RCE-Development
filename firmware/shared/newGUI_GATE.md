# Original GUI update gate: N / S / F / O

2026-10-15; static read-only audit. No updater execution or USB access.

**Matching the original application-header version and CRC does not cause this GUI to refuse or skip the update. No version bump, CRC alteration, or separate Force route is needed.** With the normal connected/device-found state, the ordinary update action enters erase, load, verify, reset. This is a host-control-flow conclusion, not proof that a physical device successfully writes or boots the new image.

The exact managed gate is:

```csharp
State != Start && !UpdateInProgress && State != Finished
    && !_isUnplugged && Connect()
```

`Connect()` accepts native `<selector> connect` exit code0. The normal permitted state is `DeviceFound`. No gate reads firmware header bytes, compares a device version, or compares application CRC. The sole embedded `.hex` is extracted unchanged, and every accepted attempt calls `EraseFirmware -> LoadNewFirmware -> VerifyNewFirmware -> ResetTheDevice`, stopping on native errors. There is no independent Force button handler or force command parameter in the managed execution paths.

Cross-package verification, using pinned stock EXEs as data:

| Package | Native selector | GUI business methods | MainWindow BAML | Native loader |
|---|---:|---|---|---|
| N | 2 | 57/58 byte-identical toC11; only selector constant differs | identical toC11 | identical toC11 |
| S | 3 | 57/58 byte-identical toC11; only selector constant differs | identical toC11 | identical toC11 |
| F | 5 | 57/58 byte-identical toC11; only selector constant differs | identical toC11 | identical toC11 |
| O | 4 | 57/58 byte-identical toC11; only selector constant differs | identical toC11 | identical toC11 |

The58 compared methods cover `AirRemoteFirmwareUpdater`, `AirRemoteFirmwareUpdateProcedure`, `MainWindow`, `ExeReader`, and `FirmwareUpdaterViewModel`. The sole method difference is one opcode byte in `deviceDetector_DoWork`: C11 selector1 becomesN2/S3/F5/O4. Referenced method/field names and string literals also match. Native loader SHA256 is `eb6a6cd69e7e3b348962b7469a560b22e2c34adf7f66172f47d21cb5cdd89f06`.

Evidence locations (existing C11 reconstructed source):

- `deep/managed_updater/csharp/AirTTLB1Updater/MainWindow.cs:30-33,63-64`: mouse action enters updater.
- `.../AirRemoteFirmwareUpdater.cs:169`: exact gate; `184-216`: update chain; `303-309`: connect; `361-368`: normal state semantics; `416-428`: native error handling.
- `.../AirRemoteFirmwareUpdateProcedure.cs:28-43`: embedded HEX raw extraction; `46-91`: erase/load/verify/reset command arguments.
- `.../ExeReader.cs:22-37`: returns child exit code without parsing device firmware version or CRC.
- `hss_port/flashable/recovery_investigation/all_vs_gui.txt:110-125,153`: existing native command-chain audit found no C8/C11 version migration or CRC-based skip.
- `deep/native_loader/native_loader_deep_review.zh-CN.txt`: native programming skips all-FF data packets, not equal app versions; extended application-version field is not consumed by the inspected flow.

All evidence paths above are beneath `analysis/air_remote_ttl_c_c11/`. JSON companion records per-package hashes, tokens, RVAs and method-body hashes.

Keep `4000..40FF` header bytes unchanged as required. This preserves the target model/version/header integrity while allowing changed application bytes at`4100+` to be delivered by the existing ordinary GUI path. Original XAML was not recovered; identical BAML is established, but no visual style/IsEnabled rendering was performed. Hardware acceptance remains a separate verification step.
