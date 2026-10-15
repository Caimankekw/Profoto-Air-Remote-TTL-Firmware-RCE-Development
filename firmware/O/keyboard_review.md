# Olympus TTL-O A4 keyboard static review

本文件对应 `keyboard_contract.json`。所有地址为 PIC18 **字节地址**。读取的候选解码文件基址为 `0x4002`，长度 49,150 字节，SHA-256 为 `AF0D4BC4A0DFA54F85D05599D9E7AE3B691317CF7F4ECBE6AD29F51ED29D8EF4`。未执行固件、USB 操作或网络请求；未修改固件。

“确认”指该候选机器码中的静态证据，物理标签另作置信说明。若后续换用 shared-stock 文件，先校验同一地址上的 preimage；不能只按地址套用。

## 主调用路径与槽

外层主循环 `0x57C0..0x57F6`，UI 更新函数 `0x5806`；`0x58D8 CALL 0x5036` 采集，`0x58DC CALL 0x9DF4` 消费。`0x5036` 先查询 `0x00AF` 的计时条件，未满足立即返回。满足时更新全部 12 个槽；`0x9DF4` 每次只消费一个槽，索引在 RAM `0x080`，乘 4 后加 `0x100`，到 12 回零。

模拟输入的机器码条件为：`field=(SFR[0xFC2]>>2)&0x0F`，`v=SFR[0xFC4]`，且 `SFR[0xF9E].bit6=1`。阈值是代码实际比较的高字节，不应直接替换成未验证的 10 位 ADC 阈值。数字输入低电平有效。

| 槽 | 92FC CALL | 输入条件 | 语义标签/置信 | 普通按下处理 |
|---|---|---|---|---|
| 100 | 5056 | PORTB.7=0 | MODE，TTL/MAN，高语义置信 | 5C12 → 6A62；RAM081 非零时改走 A4F4 |
| 104 | 50B2 | field0，13<v<53 | CHANNEL，高语义置信 | 5C5A → 8454，循环配置 +8 的 1..8 |
| 108 | 5082 | field1，53<v<C0 | SYNC，中等语义置信 | 5C38 → 8F00，配置 +2 的 2/3 |
| 10C | 50D8 | field1，v>BF | A，高语义置信 | 5C6A → 98D8，W=1 |
| 110 | 5104 | field1，13<v<53 | B，高语义置信 | 5C7C → 98D8，W=2 |
| 114 | 5124 | PORTA.2=0 且 RAM083=0 | C，高语义置信 | 5C8E → 98D8，W=3 |
| 118 | 514E | field0，v>BF | MODEL，高语义推断 | 5CA0 → RAM063..065 间接回调 |
| 11C | 517E | field0，53<v<C0 | HEAD，高语义推断 | 5CC4 → RAM066..068 间接回调 |
| 120 | 519E | PORTB.1=0 且 RAM084=0 | +，有显式正增量 | 5D0A → 4A8E/A174/5D30，仅重置计时 |
| 124 | 51B2 | PORTB.0=0 | −，有显式负增量 | 5D20 → 同一计时路径 |
| 128 | 51C6 | PORTB.6=0 | TEST 候选，低/中置信 | 5CF6 → A60C → A3C4 |
| 12C | 51DA | PORTE.1=0 | ON/OFF 候选，中置信 | 普通按下分发无动作 |

表中数值均为十六进制，区间严格排除端点。A/B/C/MODEL/HEAD 等物理印字尚无 Olympus 实物验证。MODEL 与 HEAD 同属 field0 的不同电压区间，多键模拟别名未知。

## 采样函数与事件状态机

`0x92FC` **仅采样**，参数 `RAM01E:01F=slot`、`RAM020=input`：

```c
slot[0] = (old & 0x80) |
          (((old << 1) | (input == 1 ? 1 : 0)) & 0x7f);
```

证据：`9302..930C` 判断恰好等于 1，`931A..9322` 保留旧 bit7，`9326` 仅写槽首字节，`9328 RETURN`。不能把 92FC 当成完整按键状态机。

完整消费者为 `0x596E`，指针 `RAM1E9:1EA`。槽 4 字节为：

| 偏移 | 含义 |
|---|---|
| +0 | bit0..6 为最近七次采样；bit7 为已确认按下 |
| +1 | b0 按下已发；b1 250 事件已发；b2 650 事件已发；b3 松开已发 |
| +1 其余位 | b4 抑制松开；b5 抑制两种长按事件；b6 抑制 650；b7 repeat/rearm 标志 |
| +2/+3 | 保存的 15 位计数时间戳及特殊哨兵，不是简单 elapsed |

- **按下**：`5A04..5A42` 要求旧 bit7=0 且 `(history&7)==7`。清 b3；若 b0 未置，保存时间戳、置 b0、`CALL 80F4`；最后置 history.bit7。
- **计时**：只有 `history==FF`（`596E..5972`）才计时；因此长按分支还要求七个历史位均为 1。
- **250 事件**：elapsed ≥ `0xFA`，b5/b1 不阻止时置 b1 并调 `ABC2`；`ABC2` 只有 `RETURN`。
- **650 事件**：elapsed ≥ `0x028A`，b5/b6/b2 不阻止时置 b2，尾跳 `9ED6`。
- **松开**：`5A44..5A56` 要求 history.bit7=1 且低三位为零。b3/b4 均未置时置 b3，`CALL 83B0`。无论 callback 是否执行，`5A76..5A8C` 都令 flags=08、timestamp=0、history=0，最后 `RETLW 0`。
- **repeat**：`9ED6 → 9934` 执行 `flags&=BB` 清 b2/b6，置 b7并重写时间戳。因此可再次经过 650 计数触发；b1 不清。b7 在所查 596E 内不读取。
- **抑制释放**：`A84A..A85A` 只置 flags.b4，不清历史或计时。没有发现独立的 pop/read-and-clear 事件接口；此实现使用同步 callback 和锁存标志。

普通 UI 状态 `RAM082=0` 的返回/分发流：

| 事件 | 调用链与返回 |
|---|---|
| press | 596E → 80F4；A838 资格检查失败尾跳 A84A；通过后 8110 尾跳 5C12 |
| release | 596E → 83B0 → 83B2 CALL 87BA；83FC 清 RAM086，再 RETURN |
| hold650 | 596E 尾跳 9ED6 → 9934；9EE8 尾跳 6DD0 |
| 其他 UI 状态 | 80F4/83B0 另分发 9C04、A8FE、A5C4、A5DC、A5F4；未完整审计 |

`RETLW 0/7` 等不是已确认的 scalar 按键事件编码。

## TTL/MAN 配置指针与选择回调

配置指针 `RAM07E:07F=0x0199` 的启动证据：

`57A2 MOVLW 99 → 57A4 MOVWF F3 → 57A6 MOVLW 01 → 57A8 MOVWF F4 → 57AA CALL 5520`；
`5520 MOVFF 0F3,07E`、`5524 MOVFF 0F4,07F`。全 listing 搜索仅发现这两处直接写 07E/07F。

所以 mode 为 `0199`，SYNC 候选字段为 `019B`，组补偿为 `019D..019F`，channel 为 `01A1`。

`0x6A62` 是模式切换核心：RAM081=0 时 `6A74..6A8C` 写 `config[0]=(old==1?0:1)`；RAM081 非零的直接调用路径强制写 1。随后清 RAM061，调用 `RAM06C..06E` 重选功率回调并更新计时/显示。正常 MODE 键在 RAM081 非零时先走 A4F4，不能忽略这个门控。

`config[0]==0` 使用 ±20 的组补偿字段，`config[0]==1` 使用 ±99 的相对量，强支持 **0=TTL、1=MAN**。该语义仍需与独立 LCD/实物标签证据合并。`8F00` 改的是配置 +2 的 2/3，不能误认作 TTL/MAN。

`98D8` 接收组号 1/2/3；若与 RAM060 当前组相同则选择 7，否则选择该组，尾跳 `609A`。`609A` 存 RAM060 并配置回调：

| selection | MODEL ptr063 | HEAD ptr066 | power setup ptr06C | mode0 power ptr069 | mode1 power ptr069 |
|---|---|---|---|---|---|
| 1 / A | 892C | 91DA | 9B54 | 8A4C | 90AE |
| 2 / B | 854A | 8F3E | 9B28 | 814E | 9072 |
| 3 / C | 8402 | 8DC0 | 9AFC | 8BAA | 9036 |
| 7 / all | 9C2E | 9AA4 | 9B80 | ABC0（RETURN） | 6930 |

安装证据为 `60A2..612E`，`6134..6146` 按 1/2/3/7 分支；`6148` 间接调用 setup，`614E` 尾跳 `84A6`。setup 函数调用 `5666` 读 config[0]，写三字节指针 RAM069..06B。

MODEL 候选回调操作 RAM03F 对应组位，结合 RAM02C 的组启用位，经 `8722` 更新派生状态，再尾跳 `8974`（`8996 MOVLW 8D`）。HEAD 候选回调翻转 RAM02C 对应位，全组版本在 0/7 间切换，再走 `9EB2 → 89BC`。此审查没有证明 HEAD 的直接 opcode 为 8C。

## 相对 +/− 闭环

- 短按释放：`87BA..87CA` 槽120传 `W=01`，`87CE..87DC` 槽124传 `W=FF`，均尾跳 `86D6`。
- 长按重复：`6DD0..6DE6` 槽120传 `W=0A`，`6DEA..6DFE` 槽124传 `W=F6`；此前调用 A84A 抑制随后的释放补一步。
- `86D6` 保存有符号增量到 RAM0EA，并通过 PUSH/TOSL/TOSH/TOSU/RETURN trampoline 调用 RAM069..06B。
- mode0：`8A4C/814E/8BAA` 先以 RAM02C 启用位门控，再加到 config+4/+5/+6；`818E` 设边界 `14/EC`，经 `90EA` 限制到 −20..20，再走 `876E`。all 的 ABC0 为无动作。
- mode1：`90AE/9072/9036` 加到 RAM036/037/038；`6930` 逐组处理三者。通过 `69BC` 设 `63/9D`，经 `90EA` 限制到 −99..99；都受 RAM02C 对应启用位门控。
- mode1 回到 `8716..871A` 后，增量还加到 RAM061 并 RETURN。mode0 回调后 selection=7 在 86F4 RETURN，否则尾跳 7B14。

数值与符号有明确指令证据；“每单位为 0.1 EV”尚不是本按键追踪独立证明的结论。

## 时间语义、preimage 与限制

`A4DA → AB2E` 读 RAM075:076；`8E00 → AA52` 规范化为 15 位，零映射为一，`5AB8` 写槽。elapsed 帮助函数 `98AA` 输入 CC:CD 为**槽时间戳指针**，经 `669C`：saved=0 返回0；saved.bit15=1 返回FFFF；普通路径为 `(normalize(now)-saved)&7FFF`。达到 `5DC1` 时 `6708..672A` 可能改写哨兵；本次仍返回 delta，下一次返回FFFF。真实时间单位未确认。

机器可核对的完整 preimage windows 位于 JSON。已通过 UTF-8 JSON 解析、来源 SHA-256、19 段逐字节 preimage、12 个唯一槽及全部 12 个 CALL 92FC 调用点校验。Windows PowerShell 读取这两份 UTF-8 文件时应指定 \`-Encoding UTF8\`。几个关键入口：

| 地址 | 原始字节窗口 | 含义 |
|---|---|---|
| 609A | 21 6E 21 C0 60 F0 49 D0 | 存 selection，再跳 dispatcher |
| 86D6 | 00 01 EA 6F 33 EC 2B F0 0D E1 | 存 delta、读 config[0]、分支 |
| 596E | 9B D8 DE 28 48 E1 | 读槽、检查 history==FF |
| 5A04 | 50 D8 DF BE 1D D0 4D D8 DF 50 07 0B 07 0A 18 E1 | 初次按下条件 |
| A84A | 20 EE 01 F0 1E 50 D9 26 1F 50 DA 22 00 0E DB 88 00 0C | 设置 release suppression |

关键限制 / critical limitations：

- 物理标签尚无 Olympus 实物按键验证。Physical key labels have not been verified on Olympus hardware.
- 250/650 是计数，不可直接写毫秒。250/650 are counter thresholds; milliseconds are unconfirmed.
- 首 word 未知，来源仍是候选解码。The initial word is unknown and the source remains a candidate decode.
- 非普通 UI 状态、flags b5/b6 的全部 writer、模拟多键别名尚未闭合。Non-normal UI states, all flag5/6 writers and analog multi-key aliasing remain unresolved.
- 本文件是静态契约，不是整机验证或刷写产物。This is a static contract, not full-device validation or a flashable artifact.

