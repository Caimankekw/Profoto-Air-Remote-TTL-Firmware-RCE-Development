# 原厂更新器只读检查

[English](README.md) | 简体中文

需要 Python 3.9 或更新版本，仅使用标准库。请提供本分支对应的原厂 EXE；
文件可以位于任意本地路径。不需要第二个厂商文件、Canon 更新器、安装程序或设备。

在仓库根目录运行：

```powershell
python tools/inspect_original.py --original "D:\Firmware\original.exe" --output outputs/inspection-01
python tests/test_inspect_original.py
python tests/test_inspect_original.py --original "D:\Firmware\original.exe" --other-original "D:\Firmware\another-model.exe"
```

工具始终读取仓库根部、与 `tools` 同级的 `model.json`，不受当前工作目录影响。
该文件必须保留本分支完整的原厂 profile。工具没有切换型号、profile、跳过哈希或
覆盖资源偏移的参数。完整 profile 指纹会拒绝削弱检查条件的改动；这是可重复性校验，
并非数字签名，也不防止修改工具源码本身。

检查内容包括：EXE 大小和 SHA-256、HEX 资源及其余 EXE 字节的 SHA-256、
全部 Intel HEX 校验和、稀疏地址范围与记录布局、变换表和 manifest、固定 opaque
尾部指纹、codec 往返一致性、头部 CRC/型号/版本、最后非 FF 地址，以及各输出哈希。

以下均为 MCU 绝对字节地址，右端点不包含在区间内：

| 区间 | 含义 |
| --- | --- |
| `[0x4000,0x4002)` | 明文未知；两个 `00` 仅为占位，mask 为 `00 00`，不是已恢复的零值。 |
| `[0x4002,0x10000)` | 通过固定的、依赖地址的字节变换直接解码。 |
| `[0x10000,0x1FC00)` | 只有整个 opaque 尾部匹配固定的已知 FF 指纹后，才恢复为 `FF`。不宣称任意尾部变换能力。 |

新输出目录中包含原始 `original.hex`、`original.base4000.partial.bin`、
`original.known_mask.bin`、`profile.json` 和 `inspection.json`。前四项与原厂分析
参考产物逐字节一致。partial BIN 基址为 `0x4000`、长度为 113,664 字节；mask 的
`01` 表示已知，`00` 表示未知。额外的配置字节和稀疏空洞仅保留在原始 HEX 中。
**partial BIN 仅供分析，不是可刷写固件。**

必须指定全新的输出目录。即使内容相同，已有路径也会被拒绝。全部校验通过后才创建
输出，并用独占写入避免覆盖。写入中断可能留下部分结果；工具不会删除这些结果，
请使用另一新目录重试。报告不记录传入的本地文件路径。生成的输出和测试 scratch
目录仅供本地核验，不属于待公开源码。

测试覆盖严格 HEX 解析、变换表完整性与边界、profile 篡改拒绝，以及输出冲突拒绝。
加 `--original` 可执行真实提取和单字节修改拒绝测试；再加 `--other-original` 可验证
错误型号拒绝。测试 scratch 保留在 `outputs/` 中供检查。

工具不会执行、修改或生成 EXE，也不访问网络或 USB。离线通过不代表设备验收或厂商认可。

原创检查/适配代码与解释文本版权为 Copyright (C) 2026 Caimankekw，采用
**AGPL-3.0-only**，完整协议见仓库 `LICENSE`。本工具复用并适配项目的
`shared/inspect_variants.py`、严格 `HexImage` 解析器和 `ReferenceCodec`。
随附表格是派生的字节变换参数，不是固件镜像。Profoto 原始固件、恢复的厂商指令、
更新器/loader 及其他第三方材料保留各自版权与条款。本项目不冒认这些材料的作者，
也不授予额外再分发权；使用本工具不会将提取结果重新许可为 AGPL。
