# Sony A6 display and power-control ABI / Sony A6 显示与调功接口

This directory contains offline reverse-engineering evidence and a **numeric UI component**, not a complete or flashable firmware. The original A6 HSS path is not modified. `sony_display_abi.json` binds every entry point to exact recovered preimage bytes.

本目录提供离线逆向证据及**数值显示组件**，不是完整可刷固件。不修改原厂 A6 的 HSS 路径。`sony_display_abi.json` 为各入口记录了恢复映像中的原始字节。

## Confirmed bindings / 已确认接口

| Function or state / 功能或状态 | A6 address / A6 地址 | Meaning / 含义 |
|---|---|---|
| Mode / 模式 | RAM `0x193`; reader `0x9690` | `0=TTL`, `1=MAN`; returns W and Z / 通过 W 与 Z 返回 |
| Config / 配置 | RAM `0xD2:0xD3=0x0193` | Bound by `0x5068`, from startup `0x4E7A` / 启动绑定 |
| Group selector / 灯组选择 | RAM `0x0C1`; setter `0x5CD8(W)` | `1=A,2=B,3=C,7=ALL` |
| TTL compensation / TTL 补偿 | RAM `0x197..0x199` | Signed tenths, clamp −20..20 / 有符号十分档 |
| MAN relative edits / MAN 相对调节 | RAM `0x0EC..0x0EE` | Signed tenths, clamp −99..99 / 有符号十分档 |
| HEAD / 闪光开关 | RAM `0x0DB`, bits `0..2` | A/B/C; original default `7` / 原默认全开 |
| MODEL / 造型灯开关 | RAM `0x0F3`, bits `0..2` | A/B/C; original default `0` / 原默认全关 |
| Common adjustment / 通用调节 | `0x87CC(W)` | Signed delta; stores it at RAM `0x0A3` / 输入有符号步长 |
| Native numeric refresh / 原数值刷新 | `0x6DDE` | TTL uses config FEC; MAN uses temporary relative values / TTL 与 MAN 分支 |
| Numeric formatter / 数字格式化 | `0x7584` | `6F=49`, `70=row`, `71=positive target`; BSR=0 |
| Repeated glyph / 重复字符 | `0x97D8` | Same arguments; `71=0x19` renders `--` / 同接口，显示关灯横线 |

The three LCD row addresses are `0x4A`, `0x4C`, `0x4E`. The original formatter handles all targets `1..100`: `0.1..9.9` have a decimal point; `100` is displayed as `10` with no decimal point on the two-digit display. After rendering absolute powers, clear only the sign fields: `RAM49 &= 0x3F`, `RAM50 &= 0xF0`. This preserves group-selection bits `49.1/49.3/49.5` and MODEL icons in the upper nibble of RAM50.

三行数码地址为 `0x4A/0x4C/0x4E`。原格式化函数可以处理 `1..100`：显示 `0.1..9.9`，最高档在双数码上显示无小数点的 `10`。绝对功率显示后，仅清除符号位 `RAM49 &= 0x3F`、`RAM50 &= 0xF0`，保留灯组选中框及造型灯图标。

## Shared-core renderer / 共享核心渲染器

`canonical_full_renderer.construct(original, base, state_base=..., redraw_rows=...)` now wraps the row renderer and exports `redraw`, `redraw_icons`, and `page_hint`. The complete redraw projects the visible page, selected row (ALL lights all three boxes), HEAD-gated MODEL icons, and global TTL/MAN icons directly from canonical state. It never substitutes DEF values into native ABC fields `193/C1/DB/F3`. The optional hint displays A/b/C or d/E/F in the numeric positions; the next redraw restores all three values. Its invocation and dwell time belong to the outer page-change/event flow, not a new busy wait.

完整适配器 `canonical_full_renderer.py` 已提供 `redraw/redraw_icons/page_hint`。它从共享状态投影当前页、选择框（ALL三框全亮）、受 HEAD 开关约束的造型灯图标和真实 TTL/MAN 图标；不向原 ABC 状态 `193/C1/DB/F3` 填入 DEF。辅助页提示在数码位显示 A/b/C 或 d/E/F，下一次重绘恢复功率；显示时长和调用时机交由外层事件处理，不新增忙等。

ABC uses fixed labels `49.0/49.2/49.4` ON; DEF clears those same known labels, matching P8's steady page distinction. This is not a claim that fixed DEF labels exist. Original `9CAE` sets these bits at `9CB2/9CB4/9CB6`. Original `814C` edits separate selection bits `49.1/49.3/49.5`.

ABC页点亮已知固定字样 `49.0/49.2/49.4`，DEF页熄灭，与P8的持续页标一致，不声称存在固定DEF字样。原 `9CAE` 在 `9CB2/9CB4/9CB6` 设置这些位；选中框则由 `814C` 控制另一组 `49.1/49.3/49.5`。

The fixed-label mapping is backed by the **same LCD controller/address and native serial output**, not merely by adjacent bit positions. Canon icon65/66/67 modifies shadow5F bits7/6/5 and sends controller2/address0. Sony binds LCD callbacks AF5C/A3EE/A17C in object019C (`7D78..7D9A`), selected via D4:D5 (`7E70..7E74`). Sony selector2 calls A17C/A186 and drives the same F80.3/F83.2 selection as Canon9028. A9F6 sets the first source range to eight bytes, index0; 9382/A8A6/AE32 selects controller2, 9EAA emits command101 and 9EB8 emits address0. The original byte encoders establish Sony bits0/1/2/3/4/5/6/7 ↔ Canon bits7/3/6/2/5/1/4/0. Therefore Sony49 bits0/2/4 reach the exact segments used by Canon's fixed ABC labels. `test_lcd_serial_mapping.py` replays both original encoders for all256 byte values and the native selector2 GPIO states.

上述映射经**同一LCD片选、地址及原序列化位序**确认。Canon的65/66/67分别修改5F的7/6/5位，发往controller2/address0；Sony在019C对象绑定AF5C/A3EE/A17C，通过D4:D5调用，片选2使用相同F80.3/F83.2。Sony首显示区从49、索引0开始，先发送命令101和地址0。两版线上编码证明Sony位0/1/2/3/4/5/6/7依次对应Canon位7/3/6/2/5/1/4/0，因此49的0/2/4就是同一固定ABC字样段。`test_lcd_serial_mapping.py`执行全部256字节的原编码器及片选状态，结果一致。

The native UI can overwrite these projections after a numeric hook: `9CAE` calls `6DDE` then tail-calls `8816`, which redraws MODEL from native ABC masks; `814C` also clears all selection boxes for ALL. Integration must reapply `redraw_icons` after those native updates and before actual LCD submission, or wrap all relevant original icon entries with a safe fallback. A numeric-only hook is insufficient.

原UI可在数字钩子之后覆盖投影：`9CAE`调用 `6DDE` 后还会进入 `8816` 从原ABC掩码重画造型灯，`814C`在ALL时还会清除全部选择框。集成必须在这些原更新之后、LCD真正提交前补调用 `redraw_icons`，或完整包装相关原图标入口并保留回退；不能只接数字钩子。

`final_display_hook.construct(original, base, state_base=..., redraw_icons=..., context_enter=..., context_leave=...)` provides that final projection at **52DE**, replacing exactly `490e6b6f` (`MOVLW49; MOVWF6B`) and continuing at **52E2**. Its 44-byte wrapper calls the external complete context helpers, checks runtime magic `A8` and normal UI `DD=0`, and invokes only `redraw_icons`. Invalid/uninitialized state and diagnostic pages retain the original display. It then replays both displaced instructions with the original BSR and STATUS context restored. The original change comparison and serializer remain in place.

`final_display_hook.py` 已实现上述最终投影：在 **52DE** 覆盖完整的 `490e6b6f`（`MOVLW49; MOVWF6B`），继续 **52E2**。44字节包装函数通过外部完整上下文保存器保护原现场，仅在状态魔数为 `A8` 且正常UI `DD=0` 时调用 `redraw_icons`；未初始化及诊断页维持原显示。之后在恢复原BSR与STATUS的前提下补执行被替换的两条指令，保留原变化比较和串行驱动。

The native `51DE` routine snapshots `49..53` to `2A7..2B1` before rendering, compares them at `52F0`, calls dirty helper `AEB2` at `52FE` on a change, and advances the nonblocking serializer `9E80` at `5318`. Shared-core service runs after `51DE`; without explicitly marking dirty, its new pixels could be copied into the next snapshot and escape change detection. Therefore the complete renderer's `redraw` and `page_hint` tail-call **AEB2**, which sets `E3=1`; the pure `redraw_icons` export intentionally does not. Do not restore away LCD shadow `49..53` or dirty byte `E3`, and do not mark dirty on every idle loop.

原 `51DE` 先把 `49..53` 复制至 `2A7..2B1`，在 `52F0` 比较，变化时经 `52FE` 调用 `AEB2`，再在 `5318` 推进非阻塞串行驱动 `9E80`。共享核心服务位于 `51DE` 之后，其新显示若不显式置脏，可能被下一次快照吸收而永远未触发刷新。因此完整渲染器的 `redraw/page_hint` 末尾跳转 **AEB2** 设置 `E3=1`；纯 `redraw_icons` 刻意不置脏。现场恢复不得覆盖LCD影子 `49..53` 和脏位 `E3`，空闲循环也不应反复置脏。

`test_final_display_hook.py` executes the actual parent context helpers, guard, displaced instructions, native comparison, and native cooperative serializer. Seven guard/compare cases pass. Two independent edits each finish in 27 scheduler calls and emit the expected 194 bits for the two LCD controller ranges; following idle calls emit no bits. Only physical GPIO-bit/selection boundaries and activity notification are stubbed. This verifies the software submission path, not physical LCD response or timing.

`test_final_display_hook.py` 执行父后端真实保存/恢复机器码、条件判断、原指令补偿、原比较及原协作串行器；7组保护/比较用例通过。两次独立修改各在27次调度后完成，按两片LCD范围发送预期194位，随后空闲不再发送。仅物理GPIO位/片选和活动通知边界使用测试桩，证明软件提交路径，不代表实体LCD响应或时序验证。

The current integration uses `canonical_renderer.construct(original, base, state_base=..., display_row=...)`, exporting `redraw_rows`. It queries all three rows through the shared ABI and supports blank, signed relative/FEC, absolute power, and HeadOFF `--`. `state+61` is the value returned by the core. Mixed row kinds preserve each other's sign bits. The parent backend adds canonical page/selection/model/mode icons and preserves the outer native calling context. This renderer emits sections only, with no native hook or image mutation.

当前集成使用 `canonical_renderer.construct(...)`，导出 `redraw_rows`。通过共享 ABI 查询三行，完整支持空白、相对值/TTL补偿、绝对功率和关灯横线；`state+61` 是核心返回值。每行只修改自身符号，混合行不会互相抹掉正负号。父后端负责分页、选中、造型灯、模式图标及原调用现场。本渲染器只输出代码段，不改原映像。

`test_canonical_renderer.py` executes emitted code and original numeric helpers for 968 cases, including all signed values −99..99, absolute values1..100, 64 combinations of four row kinds, invalid absolute values and neighboring LCD state. The core query is mocked; silicon RAM capacity and complete runtime integration remain separate requirements.

`test_canonical_renderer.py` 的968例执行新代码与原数字函数，覆盖全部有符号范围、绝对功率范围、64种混合行及异常值；核心查询使用测试桩。实体 RAM 容量、完整运行流程仍须由集成验证。

`test_native_ui_helpers.py` executes original selector `5CD8`, mode icons `7B3A`, and MODEL icons `8816` **without instruction hooks or peripheral stubs**. Their entire executed paths write only the documented local UI/pointer/scratch state. Valid `5CD8` selectors refresh mode-dependent callbacks after mode193 changes; never substitute whole mode toggle `78B4`, which also reaches radio-side actions. `8816` reads original ABC masks DB/F3; display of DEF must map canonical values at the LCD layer without overwriting original ABC mask semantics.

`test_native_ui_helpers.py` 无指令测试桩地执行原 `5CD8`、`7B3A`、`8816`，核对写集只有本地 UI、函数指针和临时量。写模式193后，可用有效选中参数调用 `5CD8` 更新回调，用 `7B3A` 更新模式图标；不能用含发包路径的 `78B4` 代替赋值。DEF 的造型灯图标须直接映射 LCD，不能临时把 DB/F3 改成 DEF。

## Earlier predicate component / 早期谓词组件

The following `display_adapter.py` interface is retained as bounded historical evidence. It supports all-absolute pages with original fallback and is **not the final shared-core renderer**, because TTL-DEF and AIR1 temporary rows require the four-kind interface above.

下列 `display_adapter.py` 旧接口保留作阶段证据；它支持全绝对页与原路径回退，不是最终共享核心渲染器。TTL-DEF 与 AIR1 临时数值应使用上面的四类接口。

```python
component = construct(
    original,
    base,
    targets=(address_A, address_B, address_C, address_D, address_E, address_F),
    page=page_address,
    head_mask=canonical_head_bits_address,
    absolute_predicate=shared_core_predicate_address,
)
```

All extension SRAM addresses are explicit inputs. `absolute_predicate` must return W=`1` when the core wants absolute rendering, W=`0` otherwise. The shared core owns the MAN A1/A2 and TTL DEF policy. The display component does not infer TTL DEF policy from the native TTL/MAN byte. `head_mask` is canonical six-bit A..F state. Disabled groups show the original `--` glyph. Targets for the visible page must all be in `1..100`; invalid state falls back before any digit changes.

新增 SRAM 地址全部由集成方显式传入。`absolute_predicate` 由共享核心实现：需要绝对功率显示时返回 W=`1`，否则返回 `0`。MAN A1/A2 与 TTL DEF 页策略由核心决定，显示组件不从原 TTL/MAN 字节自行推断。`head_mask` 是 A..F 六位闪光开关，关闭的灯组显示原生 `--`。当前页三个目标必须全部在 `1..100`，无效状态在修改数码前退回原路径。

The only generated patch replaces the complete four-byte `CALL 9690` at `6DDE` with a GOTO to the component. Fallback executes the displaced call and continues at `6DE2`, preserving its mode result and flags. Native MAN timeout code `8062..808A` can still clear `EC..EE`; canonical A2 targets must therefore be separate.

唯一生成的原程序补丁是将 `6DDE` 完整四字节 `CALL 9690` 替换为跳转。原路径补执行该 CALL，并在保留模式返回值与标志后继续 `6DE2`。原 MAN 超时路径仍会清除 `EC..EE`，因此 A2 绝对目标必须独立保存。

Some original HEAD and relative-edit handlers call `89D0` directly. The core must explicitly refresh after an A2 action or own those handlers. A single `6DDE` hook does not implement AIR2 or suppress native relative commands.

部分原 HEAD 与相对调功回调直接调用 `89D0`。核心需要在 A2 操作末尾显式刷新，或接管这些回调。单独修改 `6DDE` 并不能实现 AIR2，也不能阻止原相对命令发送。

For a power-control integration, `87CC` must cover **six** bytes (`MOVWF A3` plus the full `CALL 9690`). A four-byte overwrite would split the CALL. This component reports that ABI and preimage but does **not** implement the radio/power core.

集成调功时，`87CC` 必须覆盖**六字节**，即 `MOVWF A3` 加完整 `CALL 9690`；只覆盖四字节会截断指令。本组件只记录此接口及原字节，不实现射频或绝对功率控制核心。

## Checks and limitations / 校验及边界

```powershell
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/build_display_evidence.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_display_adapter.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_canonical_renderer.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_native_ui_helpers.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_canonical_full_renderer.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_lcd_serial_mapping.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/test_final_display_hook.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/S/display/keys/test_native_keys.py
```

The tests execute the original PIC18 formatters and the new wrapper in the existing bounded offline VM. The external core predicate is mocked. They check both pages, target boundaries, every six-group HEAD mask, sign/selection preservation and original-branch entry state. They do not validate timing, SRAM silicon availability, complete core policy, radio delivery, startup or USB flashing.

测试通过现有受限 PIC18 离线 VM 执行原格式化代码和新包装函数，共享核心判断函数使用测试桩。覆盖两页、功率边界、全部六组 HEAD 掩码、符号及选中框保留、原路径入口状态。不等同于时序、实体 SRAM、完整核心模式、射频、开机或 USB 刷写验证。

The original A6 occupies more RAM than Canon C11: `2A4..2A5` is a pointer, `2A6` a flag and `2A7..2B1` an eleven-byte buffer. `500..5FF` has no direct MOVLB/MOVFF/LFSR references in the recovered body, but that alone does not prove absence of indirect aliases or silicon SRAM coverage. Tests use `500..508` only as VM fixture addresses. Final allocation and initialization belong to integration.

A6 原程序占用 RAM 多于 Canon C11：`2A4..2A5` 为指针、`2A6` 为标志、`2A7..2B1` 为 11 字节缓冲。恢复程序中没有 `500..5FF` 的直接 MOVLB/MOVFF/LFSR 引用，但这不能单独证明没有间接别名或芯片确实提供该 RAM。测试中的 `500..508` 只是 VM 地址，最终分配及初始化由集成方负责。
