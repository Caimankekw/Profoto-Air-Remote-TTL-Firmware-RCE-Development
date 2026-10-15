# Air Remote TTL-F · Fujifilm AIR2-P8-M2

[English](README.md) | 简体中文

开发者：**[Caimankekw](https://github.com/Caimankekw)** · 原创内容：[AGPL-3.0-only](LICENSE)

本实验固件**仅适用 Fujifilm Air Remote TTL-F，原厂输入 A5**。当前为 [fujifilm-air2-m2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-air2-m2) 开发分支；未修改固件的逆向见 [fujifilm-a5](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/fujifilm-a5)。[Release fujifilm-air2-m2-20261016](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/releases/tag/fujifilm-air2-m2-20261016) 提供 Windows 包及对应源码。

**本型号尚未确认实机启动、相机/无线及掉电行为。** 离线检查及 Canon 实测不能替代本型号验证。本次保留现有 M2 固件字节，补充型号专属发布、构建和封包入口；保留本型号原厂 HSS，不使用 Canon HSS-P3。

## 操作与修复

- MAN AIR1 相对调节，编辑后临时显示数值；MAN AIR2 为绝对目标，当前页已开启组持续显示。
- C＋HEAD 切换 ABC/DEF；MAN 下 C＋MODEL 切 AIR1/AIR2。TTL 吞掉后者，不改上次手动类型。
- A、B、加减键使用正常路径；忙事务仍可能拒绝编辑，不保证任意连按速度。
- MODE 返回记住的手动类型；保存六组 AIR2 目标、Head/Model 开关、模式及页面。
- ALL 影响六组。**TTL 的 ABC 为曝光补偿，DEF 按上次手动类型控制，不是六组自动 TTL。** AIR2 数值为请求值，不是灯端反馈。

M2 修复启动模式变化覆盖已保存开关、AIR1 到期遇忙无法再清屏，以及 Fujifilm 的 TTL/DEF 到期和 ALL 选框、Sony 翻页提示和松键重绘。只有所属型号的代码路径执行。若旧 M1 已保存错误开关状态，升级后请核对并重设全部 Head/Model。存储写入或读回失败后，本次上电停止重试，下一次启动重新尝试；这与 Canon 保留脏状态再试的策略不同。详见[完整行为与边界](firmware/README.zh-CN.md)。

## 构建和目录

使用 Python 3.9+，自行提供未修改的 `Air-Remote-TTL-F-Firmware-A5.exe`，无需旧工作目录或 Canon EXE。

```powershell
python -B build.py --original "C:\firmware\Air-Remote-TTL-F-Firmware-A5.exe" --output "build\M2"
python -B tools/package_source.py --out "artifacts"
```

输出路径必须新建。根构建器绑定 TTL-F，核对输入和源码指纹，在保留的隔离目录中以独立进程构建，不运行更新器或访问 USB。[release_profile.json](release_profile.json)固定源码和结果，[model.json](model.json)固定原厂输入。

| 目录 | 内容 |
| --- | --- |
| `reverse/`、`tools/inspect_original.py`、`tools/reference/` | 原厂证据和只读提取 |
| `firmware/` | 完整冻结的 125 文件 M2 依赖与测试 |
| `build.py`、`tools/package_source.py` | 绑定型号的入口及对应源码封包 |
| `windows/` | Windows 自解压和便携包构建 |
| `tests/` | 发布与构建检查 |

共享源码保留其他型号适配器，因为验证和封包需要其 profile。根入口只构建 TTL-F，包内不含其他型号固件。内层文档描述历史冻结 M2 源码包，本根文档描述新增 Windows 封装。通用变换参数不是厂商固件镜像；源码不带厂商 EXE、完整 HEX/BIN 或设备采集。

| 固定产物 | SHA-256 |
| --- | --- |
| 自定义 GUI 更新器 | `ac0fbd824a6fa23c754b352e7293caa2675500d6921188153c012272cdc0e3de` |
| 局部分析镜像 | `edf60a81b787b0548f481133f899fc3f58b7f5a1ce4d5194cb90826600e6e1e5` |

首两字节明文仍未知，**不能直接刷局部 BIN**。请使用对应 GUI。原更新器 GUI/加载器外壳保留，资源变化可能使原签名失效。

## Windows 包与验证

自解压 EXE 和便携 ZIP 附自定义 GUI、对应原厂恢复 GUI、完整对应源码、中英文说明/免责声明、AGPL 和第三方许可。解压不刷写；更新需在 GUI 手动操作，恢复能力不作保证。封包方法见 [Windows 说明](windows/README.zh-CN.md)。

冻结 M2 记录本型号在普通/优化 Python 下各通过 78 项整合、24 项启动恢复和 102 项专项检查。跨型号证据包含 1,024 个正常无线帧对照，以及每型号 26 条轨迹/178 步与 Canon 匹配；忙态准入仍有差异，均为有边界的软件检查。既有独立源码包重建已精确复现 EXE/HEX/局部镜像。本次还会对各分支归档独立重建并静态核对封包，结果见 Release 验证文件；封包不运行安装程序、更新器或设备。

请阅读[免责声明](DISCLAIMER.zh-CN.md)、[许可范围](NOTICE.zh-CN.md)、[LICENSE](LICENSE)及[更新记录](CHANGELOG.zh-CN.md)。AGPL 仅覆盖原创内容，厂商固件和混合二进制保留各自条款。
