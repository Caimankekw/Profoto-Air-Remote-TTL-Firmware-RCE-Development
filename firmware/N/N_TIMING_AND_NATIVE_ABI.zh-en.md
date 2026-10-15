# Nikon C5 AIR2 native adapter / Nikon C5 AIR2 原生适配

本文件记录离线实现依据，不表示设备已刷写或实机验收。最终安装包由公共链接、校验和封包流程生成。本目录没有执行更新器或访问 USB。

This document records the offline implementation evidence. It does not claim device flashing or hardware acceptance. Final installers belong to the common linking, qualification and packaging process. No updater or USB device was executed or accessed here.

## 时间基准 / Time base

| 项目 / Item | 已确认依据 / Evidence |
| --- | --- |
| Raw tick | `RAM11B:11C`, little endian; `7124`, specifically `716E..7174`, adds over the full 16-bit range. |
| Mask | `FFFF`. The `7FFF` mask belongs to the separate encoded deadline getter `A2D0 → 8B8C → A8DA`, not the raw tick used here. |
| Normal clock design | `9912 → A678` selects `30`: PLL enabled, Timer5 prescale 8, software divisor 1500. Nominal `48 MHz / 4 / 8 / 1500 = 1 kHz`. |
| Low clock design | `10`: PLL disabled, prescale 1, divisor 4000. Nominal `16 MHz / 4 / 4000 = 1 kHz`. |
| Original sampling | `4D44`, `4EB6 → 846A`: next key sampling interval 5 native counts. `8E62` shifts history; `4F64..4F68` requires three active samples. |
| Original hold thresholds | 250 counts at `4EEC..4EF6`, 650 at `4F32..4F3A`. |
| Added gesture policy | 200-count chord window, 20-count stability interval. The latter is four native sampling intervals. |
| Page cue | 650 native counts showing `A / b / C` or `d / E / F`, then canonical row values. |

正常设计下约为 200 / 20 毫秒；不得称为精确毫秒。`7124` 使用严格的 `delta > divisor`，并在更新后丢弃余数；没有测量 bootloader 时钟交接、实际振荡器和调度延迟。新增逻辑没有修改 Timer5 或 HSS 的任何参数。

The design suggests approximately 200 / 20 ms in normal operation, not calibrated millisecond guarantees. `7124` uses strict `delta > divisor` and discards the remainder. Bootloader clock handoff, the physical oscillator and scheduling latency were not measured. The adapter changes no Timer5 or HSS parameter.

## 状态与模式应用 / State and mode projection

原生 `model = *(49:4A) = 01B1`，`model[0]` 为 `0=TTL / 1=MAN`。ABC 补偿在 `model[4..6]`，选择行为 `RAM60 = 1/2/3/7`。Head 与 Model 原生掩码分别是 `4C / 50`。即便显示 DEF，仍只向这些原字段投影 canonical ABC 的低三位。

The native model is `*(49:4A) = 01B1`; `model[0]` encodes `0=TTL / 1=MAN`. ABC FEC occupies `model[4..6]`; selected row is `RAM60 = 1/2/3/7`. Native Head and Model masks are `4C / 50`. These fields retain canonical ABC low-three-bit meanings even while DEF is displayed.

模式变化保留原厂无 RF 的副作用：写模式、清 `61`、调用 `A83C(0)`、通过 `9EEC → 56D4` 更新原期限、调用 `5986` 重绑组和模式回调、调用 `7756` 更新图标。不调用含有额外 RF 的原 `7B88 / 94CA` 整条路径。请求全部参数先校验，任何失败均在原生状态写入之前返回。

Mode changes preserve the original no-RF side effects: update mode, clear `61`, call `A83C(0)`, update the original deadline through `9EEC → 56D4`, rebind group/mode callbacks with `5986`, and update icons with `7756`. The complete `7B88 / 94CA` paths contain extra radio actions and are not called. All requested parameters are validated before native state is written.

## 三种独立资格 / Three independent readiness domains

| Flag | Requirements |
| --- | --- |
| Edit, bit0 | Valid model pointer/mode/selector; ordinary application `4D=0`; original `A6C6` permission; `4B=85=1B8=0`. |
| Radio, bit1 | Edit conditions plus native transaction engine `02BA=0` and TX count `95=0`. |
| NVM, bit2 | Radio conditions plus released keys, core gesture `18=0`, core TX plan `28=0`, RX count `1CC=0`, ISR marker `53.bit1=0`, pending `FF0.bits0/1=0`, UART RX pending `F9E.bit5=0`, and UART TX shift register empty `FAD.bit1=1`. |

这些是当前快照的资格，不保证此后不会发生相机事件。普通无线忙碌不直接锁住纯 UI 编辑。`tx_frame` 和 `apply_native_state` 都重新读取资格；NVM 后端会在每次擦写前、关中断的短临界区中再次调用真实 `read_inputs`。该采样函数不修改中断使能位。

These are snapshot conditions, not a promise that no future camera event occurs. Ordinary radio activity does not by itself block pure UI edits. Both `tx_frame` and `apply_native_state` refresh readiness. The shared NVM backend calls the real sampler again inside the brief masked-interrupt region before each erase/write. The sampler never changes interrupt-enable bits.

## 无线与中断 / Radio and interrupts

原 `9D54` 使用低八位源指针 `18`，因此 16 字节帧先复制到原缓冲 `1D..2C`。原队列为 descriptor `93..98`、backing `0400..0463`、容量 100；普通记录是标记 `00` 加 16 字节。适配层每次只在原队列空且 engine idle 时提交一帧，随后保留原 `RSGT1` / UART 调度。

Native `9D54` uses an eight-bit source pointer in `18`, so the 16-byte frame is first copied into the original `1D..2C` buffer. Its queue descriptor is `93..98`, backing `0400..0463`, capacity 100; ordinary records contain marker `00` plus 16 bytes. The adapter admits one frame only when the original queue is empty and its engine is idle, retaining the original `RSGT1` / UART scheduler.

`4108` ISR 的直接调用闭包为 149 条指令，没有 TX 生产者或间接调用。异步写 `53.bit1 / 85 / 1B2 / 1B8` 和原 RX 队列，不写新增上下文保存区。ISR 临时区 `01..0C` 不被外层恢复覆盖。FSR1/2 和 W/STATUS/BSR 按原中断机制恢复，闭包不修改 FSR0、PROD、TBLPTR、TABLAT 或 PCLATH。入队没有新增关中断段。

The direct reachable closure of ISR `4108` contains 149 instructions, no TX producer and no computed call. Its asynchronous writes to `53.bit1 / 85 / 1B2 / 1B8` and the original RX queue are excluded from outer restoration. ISR scratch `01..0C` is likewise excluded. Original interrupt handling restores FSR1/2 and W/STATUS/BSR; the closure does not modify FSR0, PROD, TBLPTR, TABLAT or PCLATH. Enqueue adds no interrupt-masking region.

## UI hook 和原行为 / UI hooks and native behavior

| Original address | Replacement scope |
| --- | --- |
| `4CF2` | Explicit core/provider initialization after original application initialization, replaying displaced instructions. |
| `4D30` | Original `A352` scheduler first, then nonblocking shared service. |
| `512A` | Compose canonical LCD values, restore native arguments, then original `9BEE` serializer. |
| `55EC` | A/B direct selection; C/MODEL/HEAD shared chord arbitration. MODE/channel/TEST and other paths replay their original instructions. |
| `7E0A` | Original signed short/hold steps `±1 / ±10` sent directly to shared power edit; never fall through to native relative transmission after a handled/rejected core event. |
| `7B5C` | Extend the original idle deadline to TTL-DEF AIR1. |
| `7B72` | Clear shared AIR1 transient values on the original deadline. |

原 `8630` 释放和 `6786` 长按分派没有 C/HEAD/MODEL 副作用，因此无需额外改写。外层保存原 `0D..46 + C0..F1` 和 16 个架构寄存器，共 124 字节，位于 provider `C0..13B`；不恢复状态、回调、LCD 结果或异步相机事件。原 MAN、TTL 图标不闪烁；AIR2 通过三个常驻绝对功率辨识。DEF 固定 ABC 字样隐藏，并通过短暂 d/E/F 页提示辨识。

Original release dispatcher `8630` and hold dispatcher `6786` contain no C/HEAD/MODEL side effect, so they need no additional rewrite. Outer wrappers save `0D..46 + C0..F1` and 16 architectural registers, 124 bytes in provider `C0..13B`. They do not roll back native state, callbacks, LCD output or asynchronous camera events. The original MAN/TTL icons do not blink; AIR2 is identified by three persistent absolute values. DEF hides the fixed ABC labels and displays a temporary d/E/F page cue.

## 存储和验证边界 / Storage and verification limits

原程序 journal `1F800..1FBFF` 保持不写。共享 V5 双页后端使用原全 FF 的 `F800..FBFF / FC00..FFFF`，独立执行读回与提交校验。N 的本地 `nv_load / nv_commit` 仅是默认返回失败的占位入口；最终链接器用经过验证的共享后端替换导入。`port_profile.json` 显式选择这些区域与资格，没有设置最终 `offline_qualification_complete`。

The original program journal `1F800..1FBFF` remains untouched. The shared V5 dual-page backend uses the original all-FF `F800..FBFF / FC00..FFFF` pages with readback and commit validation. N's local `nv_load / nv_commit` are default failure stubs; the final linker replaces their imports with the verified shared backend. `port_profile.json` selects these pages and gates explicitly but does not set final `offline_qualification_complete`.

当前有真实 PIC18 原指令与共享 core 的有限回放，结果在 `native_backend_test_results.json` 和 `native_hooks_test_results.json`。这不等于实际无线时序、刷写、启动或相机曝光验收。实际发布需绑定最终镜像、完整源文件哈希、跨中断/RAM审计和公共集成结果。

Bounded replay executes real PIC18 native instructions and the shared core; results are in `native_backend_test_results.json` and `native_hooks_test_results.json`. It does not establish physical radio timing, flashing, startup or camera exposure acceptance. Publication requires the final image, exact source hashes, interrupt/RAM audit and common integration results.
