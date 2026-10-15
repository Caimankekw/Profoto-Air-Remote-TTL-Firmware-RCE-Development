# Sony A6 native key adapter / Sony A6 原按键适配

This component sends **C, MODEL and HEAD normal-application press events** to deferred gesture handling. A/B call core `select_row` immediately, with no chord wait, so TTL-DEF AIR1 selection also clears canonical temporary values correctly. Original sampling, debounce and plus/minus dispatch remain intact. Shared AIR2 core owns gesture policy; this component does not implement another chord timer.

本组件把正常界面的 **C、MODEL、HEAD 按下事件**交给延后手势处理。A/B 即刻调用核心 `select_row`，不进入组合键等待，并确保 TTL-DEF 的 AIR1 选组也正确清理临时值。保留原采样、消抖和加减分发。组合键策略由共享核心负责。没有修改 HSS，也没有生成可刷包。

| Evidence / 证据 | Address / 地址 | Confirmed behavior / 已确认行为 |
|---|---|---|
| Raw classifier history / 原输入历史 | `930E` | Shift low 7 history bits, retain active bit7; append `pressed == 1` / 移入最新样本，保留活动位 |
| Native object FSM / 原按键状态机 | `5348` | Three consecutive samples for press/release / 连续三样本按下或释放 |
| Normal gated press / 正常界面按下 | `80F2 → 8116 → 595A` | Activity/input gate and `DD=0` already evaluated / 已完成输入门控与界面判定 |
| Release / 释放 | `85FE → 8782` | C/MODEL/HEAD have no semantic dispatch / 三键无调节动作 |
| First hold / 首次长按 | `AF5A` | Native threshold250 counts; function is RETURN / 250计数阈值，原回调为空 |
| Long hold / 持续长按 | `A134 → 6A96` | Native threshold650 counts; three keys have no semantic dispatch / 650计数阈值，三键无调节动作 |

Counts above are native clock counts, **not a measured millisecond calibration**. Tests execute original `930E`, `5348` and its timestamp arithmetic, observing the four callbacks. The 650-count callback is mocked in the threshold test, so that test checks the FSM's one-shot bit but does not claim the native repeating hold schedule. Separate tests execute original C/MODEL/HEAD release and long handlers with activity/flag helper boundaries mocked.

以上时间是原时钟计数，不能直接标作毫秒。测试执行原 `930E`、`5348` 及时间戳运算并观察四类回调；阈值测试把650计数回调作为测试桩，因此验证一次性标志，不声称模拟了原长按重复节奏。另行执行三键的释放和长按处理，活动通知与标志更新辅助函数作为测试边界。

## Integration / 集成

`native_key_adapter.construct(original, base, state_base=..., secondary_press=..., select_row=..., context_enter=..., context_leave=...)` verifies the complete original tail GOTO preimage at `8116`: `ad ef 2c f0`. Runtime magic at `state_base` must equal `A8`; otherwise every key keeps native dispatch. Incoming `AB:AC` is the native object pointer. C `0125`, MODEL `0129`, HEAD `012D` map to `secondary_press(W=1/2/4)`; A `011D` and B `0121` map directly to `select_row(W=1/2)`. Remaining keys continue at `595A`.

构造器核对 `8116` 四字节跳转及运行状态魔数 `A8`；未初始化时所有键保持原分发。`AB:AC` 是原对象指针。三键交给手势，A/B 即时选组，其余原路继续。集成方必须提供**完整原调用现场保存与恢复**，包括活动的 `2A4:2A5`、原编译器局部临时量和寄存器。现有现场函数是测试桩，不能据此宣布整个固件现场正确。

`construct_sampler(base, state_base=...)` emits a separate pure raw-history sampler for the shared `read_inputs`: it writes only `state+7A` (C=1/MODEL=2/HEAD=4) and `state+7B` (any other key). It reads bit0 of all eleven native objects, not active bit7. It neither clears native history nor changes native debouncing.

独立采样组件只写共享 ABI 的 `7A/7B`，读取全部11个原对象的最新样本 bit0，忽略活动锁存 bit7。不清原历史，不重新读取 ADC，不改变原消抖。

## Readiness / 可编辑条件

`DD=0` is normal application dispatch. Nonzero DD selects original special/diagnostic states; for example display strings include HELLO, A6, rAdio and G I t. Core gestures must not bypass that classification.

`DD=0` 是正常界面，非零为原专用/诊断分支。不能绕过原界面分类直接识别组合键。

`DC` is **not proved to be a channel-edit flag**. `9D5E(W)` stores it; W=1 arms a 500-count deadline. `9708` forces MAN if DC is nonzero while mode is TTL, and clears DC on timeout. MODE dispatch chooses `78B4` or `A72A` according to DC. Direct recovered calls to `9D5E` at `6C0E` and `A028` pass zero. A conservative DC=0 edit guard is possible, but labeling DC as “channel settings” exceeds the evidence. Radio and exclusive foreground readiness remain the parent backend's responsibility.

`DC` 尚不能称为“频道编辑状态”。已知其非零时影响 MODE 路径和 TTL/MAN，设置函数可建立500计数截止时间；当前直接调用均传0。可以将 DC=0 作为保守附加门控，但不得虚构 UI 含义。射频和独占状态门控由父后端继续核实。

Run / 执行：

```powershell
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/keys/test_native_keys.py
```

Existing checks cover eleven native FSM cases, eleven dispatch identities and all 2048 raw-key combinations. These are offline instruction checks, not hardware input latency measurements or a complete AIR2 integration test.

现有检查覆盖11个原 FSM、11个分发身份、全部2048个原样本组合；属于离线指令验证，不等于实体按键延迟测量或完整 AIR2 集成测试。
