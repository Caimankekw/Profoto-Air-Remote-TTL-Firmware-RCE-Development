# Fujifilm A5 原厂固件逆向

[English](README.md) · [身份信息](../model.json) · [精简原厂契约](original_contract.json) · [证据索引](provenance.json)

本分支记录 **Air Remote TTL-F A5** 的部分原厂行为。C-like 文件是说明性逆向伪代码，**不是厂家完整 C 源码，也不能编译成固件**。`native_*` / `opaque_*` 表示省略内部细节的原厂函数，不代表这些算法已经恢复。AIR2-M2 开发内容属于独立分支。

| 模块 | 原厂程序字节地址 | 范围 |
|---|---|---|
| [键盘与时钟](pseudocode/keyboard_clock.c) | `48EA`、`97C0`、`A50E`、`581A`、`7050`、`B202`、`AB22` | 对象采样、事件分派边界、原生计数算法 |
| [三组 UI](pseudocode/ui_abc.c) | `7ED4`、`9EBE→6492`、`8D7E`、`7AD2`、`6E7E`、`A6BA` | TTL/MAN、A/B/C/ALL、回调与 LCD ABI |
| [无线队列](pseudocode/radio.c) | `B2CE`、`9562`、`A60A`、`84D6`、`7174`、`864C` | 类型 2、16 字节主体、原厂准入与封装 |
| [启动与 NVM](pseudocode/nv_startup.c) | `5F6E`、`4C3A`、`6AAC`、`9BAC`、`A3DE` | 初始化、日志描述符与原厂写入序列 |
| [相机/HSS 边界](pseudocode/hss_boundaries.c) | `4108..41C4`、`5D42..5E6A`、`614C..62F4` | 仅审计过的入口和调用边界 |

`VERIFIED` 表示原指令、固定原始字节或离线指令审计支持的结论；`INFERRED` 表示物理键名、无线休眠含义等语义推断；`UNKNOWN` 表示尚未闭合。它们均不等同于相机、RF、灯具或 HSS 实机验证。

原厂 `A60A` 向 `9562` 请求检查的是 **16 字节**：`requested <= 31 && count + requested < capacity`，随后写入标记 0 和 16 字节主体。开发版检查完整 17 字节属于另加逻辑。原厂 Flash 函数清除 `FD0.7` / `FF2.7` 后，会在启动操作后**无条件置回两位**；保存旧状态再恢复是开发版改进。原厂 UI 只有 A/B/C 与 ALL，没有 D/E/F 页面。

`model.json` 原样保留 stock profile 的身份和容器范围。分析映像为 `[0x4000,0x1FC00)`，首字 `[0x4000,0x4002)` 未知，零占位不是恢复的指令。参考解码器读取 `[0x4002,0x10000)`；`[0x10000,0x1FC00)` 的 FF 判定来自不透明编码与已知 FF 参考的指纹一致，并非独立解码。低于 `0x10000` 的最后非 FF 结束位置为 `0xB2E0`（不含），不能据此证明可执行边界或空闲 Flash 所有权。索引内所有证据窗口均位于解码范围内。

`provenance.json` 保存原工作区相对来源及 SHA-256，以及本地 stock 分析映像内的半开地址窗口和哈希。来源路径用于追溯，不是公开包的运行依赖。候选线性 listing 可能把数据解作指令，因此只摘要已审阅窗口。本包不含厂家更新器、HEX/BIN、大型 listing 或设备采集数据。

整理过程中没有运行 EXE、设备、USB 或网络操作。完整 HSS 算法、真实时间单位、bootloader 行为和所有间接 RAM 所有权仍未知；本原厂契约不继承 AIR2 的资格声明。
