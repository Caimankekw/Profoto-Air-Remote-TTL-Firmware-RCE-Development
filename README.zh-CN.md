# Profoto Air Remote TTL · 逆向与 AIR2 开发

[English](README.md) | 简体中文

开发者：**[Caimankekw](https://github.com/Caimankekw)** · 原创内容：[AGPL-3.0-only](LICENSE)

本仓库整理 Nikon、Sony、Fujifilm、Olympus 四款 Air Remote TTL 的原厂固件逆向和实验 AIR2 开发。`main` 为导航页；每品牌各有一个原厂逆向分支及一个开发分支。Canon 保留在[独立仓库](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Canon-Firmware-RCE-Development)。

| 卡口 | 原厂固件逆向 | 开发分支 | Windows 更新包 |
| --- | --- | --- | --- |
| Nikon · TTL-N | [C5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/nikon-c5) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/nikon-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/nikon-air2-m2-20261016) |
| Sony · TTL-S | [A6](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/sony-a6) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/sony-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/sony-air2-m2-20261016) |
| Fujifilm · TTL-F | [A5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-a5) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/fujifilm-air2-m2-20261016) |
| Olympus · TTL-O | [A4](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/olympus-a4) | [AIR2-P8-M2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/olympus-air2-m2) | [Pre-release](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/olympus-air2-m2-20261016) |

逆向分支提供注释伪代码、地址/ABI 证据及只读提取工具，需自行提供原厂更新器。这是已恢复的局部逻辑，**不是厂商完整 C 源码**，不含 AIR2 修改或厂商固件镜像。开发分支额外提供冻结的 AIR2-P8-M2 源码、绑定本型号的构建入口及 Windows 封包代码。共享依赖与测试完整保留，根构建入口仅生成所属分支的型号。

AIR2 提供手动绝对功率、ABC/DEF 分页、C＋HEAD 翻页、C＋MODEL 切换手动类型、AIR1 数值到期清除及参数保存。TTL 的 ABC 仍为曝光补偿，DEF 按上次手动类型控制，不是六组自动 TTL。各型号保留自己的原厂 HSS，不移植 Canon HSS-P3。

**四款 M2 均为实验预发布：已有离线验证，尚未确认实机启动、无线、相机曝光及掉电行为。** Canon 的实测结果不能视为其他卡口已通过。仅使用与引闪器型号完全匹配的更新器，并阅读[免责声明](DISCLAIMER.zh-CN.md)及[许可范围](NOTICE.zh-CN.md)。

各 Release 提供 Windows 自解压安装包、便携 ZIP、对应源码、校验值、中英文说明和免责声明。Windows 包附对应原厂恢复 GUI 及第三方许可；解压不等于刷写，更新需在 GUI 手动执行。附带恢复程序不保证恢复成功。厂商固件和更新器保留原有权利，AGPL 适用于本项目原创内容。
