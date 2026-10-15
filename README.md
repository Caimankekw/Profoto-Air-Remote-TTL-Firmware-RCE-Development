# Air Remote TTL-N · Nikon C5 original firmware

English | [简体中文](README.zh-CN.md)

Developer: **Caimankekw** · Authored analysis/tools: [AGPL-3.0-only](LICENSE)

This branch documents recovered portions of the **unmodified Nikon Air Remote TTL-N C5** firmware. [Reverse-engineering notes](reverse/README.md) contain annotated pseudocode, native function/RAM contracts and evidence. Unresolved helpers remain explicit. This is not a complete vendor source tree or a rebuildable original firmware project, and contains no AIR2 patches. For custom firmware, use [nikon-air2-m2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/nikon-air2-m2); other brands are listed on [main](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development).

## Read-only extraction

Use Python 3.9 or later and an unmodified `Air-Remote-TTL-N-Firmware-C5.exe`:

```powershell
python -B tools/inspect_original.py --original "C:\firmware\Air-Remote-TTL-N-Firmware-C5.exe" --output "build\stock"
```

The output directory must be new. [model.json](model.json) fixes the input identity; the required EXE SHA-256 is `4fa0d7c1ae8201910e0586eef30feadb9230e3c30c7b67b8dc4c2d344dea5591`. See [tool instructions](tools/README.md). Extraction does not run the updater, write hardware or produce a modified EXE.

Only `[0x4002,0x10000)` has the recovered generic byte transform. The first two plaintext bytes remain unknown placeholders. The higher FF tail is tied to a known opaque suffix fingerprint, not a general-purpose decoder for arbitrary tail content. The local partial BIN is an analysis artifact and must not be directly flashed.

The HSS evidence covers identified stock call paths and intervals, not a complete recovered HSS algorithm or measured physical timing. See the [disclaimer](DISCLAIMER.md), [license scope](NOTICE.md) and [LICENSE](LICENSE). Vendor code retains its own rights.
