# Profoto Air Remote TTL · reverse engineering and AIR2

English | [简体中文](README.zh-CN.md)

Developer: **[Caimankekw](https://github.com/Caimankekw)** · Authored work: [AGPL-3.0-only](LICENSE)

This repository contains original-firmware analysis and experimental AIR2 firmware development for Nikon, Sony, Fujifilm and Olympus Air Remote TTL transmitters. `main` is the navigation branch. Each brand has a separate original-analysis branch and a matching development branch. Canon remains in the [separate Canon repository](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Canon-Firmware-RCE-Development).

| Camera mount | Original firmware analysis | Development | Windows packages |
| --- | --- | --- | --- |
| Nikon · TTL-N | [C5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/nikon-c5) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/nikon-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/nikon-air2-m2-20261016) |
| Sony · TTL-S | [A6](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/sony-a6) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/sony-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/sony-air2-m2-20261016) |
| Fujifilm · TTL-F | [A5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-a5) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/fujifilm-air2-m2-20261016) |
| Olympus · TTL-O | [A4](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/olympus-a4) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/olympus-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/olympus-air2-m2-20261016) |

Original-analysis branches contain annotated pseudocode, address/ABI evidence and a read-only extractor for a user-supplied stock updater. These are recovered portions, **not complete manufacturer C source**. They contain no AIR2 patch or distributable vendor firmware image. Development branches add the frozen AIR2-P8-M2 source, model-bound build entry point and Windows packaging sources. The shared dependency/test closure remains complete; the root build selects only its branch's model.

AIR2 adds absolute manual targets, ABC/DEF pages, C + HEAD page selection, C + MODEL manual-type selection, temporary AIR1 values and settings persistence. TTL ABC remains exposure compensation; DEF uses the remembered manual type. This is not six-group automatic TTL. Each model retains its own stock HSS; Canon HSS-P3 is not ported.

**The four M2 ports are experimental pre-releases, with offline validation but no confirmed hardware boot, radio, camera exposure or power-loss validation.** Canon hardware results do not transfer to these models. Use only the updater matching the exact transmitter model. Read the [disclaimer](DISCLAIMER.md) and [license scope](NOTICE.md).

Each release supplies a Windows self-extracting package, portable ZIP, corresponding source archive, checksums, bilingual documentation and disclaimers. Windows packages include the matching unmodified recovery GUI and vendor notices. Extraction does not flash the device; updating is a manual operation in the GUI. Recovery is not guaranteed. Vendor firmware and updater components retain their own rights; AGPL applies to the project's authored work.
