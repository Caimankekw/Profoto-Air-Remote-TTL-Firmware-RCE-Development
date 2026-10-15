# Olympus A4 native mode / boot projection contract

范围：恢复出的 Olympus AirRemote TTL-O A4 应用，PIC18 **byte address**。离线分析与原字节 VM 回放；未操作设备、USB、网络或厂商 EXE。`mode_transition_contract.json` 保存 SHA256、精确 preimage、静态闭包、调用目标和边界；`test_mode_transition.py` 可直接回归。这里只分析状态投影，不授权固件烧写。

结论：可以在主循环正常上下文、所有前置条件通过后，暂置原 radio-inhibit `RAM[02A]=1`，仅在目标 native mode 与当前不同的时候调用 **原 `6A62`**，再归还 `02A=0`。该链完整保留原计时器、模式回调、sync 字段和 LCD 副作用，同时原 `85EA` 在 `85EC..85F0` 提前返回，阻止即时 TTL `25` 发包。它不是只写 `199`。此结论依赖下述已闭合回调和 IRQ 指针不变量，不能泛化为任意调用期间可借用 `02A`。

## `6A62` 的全部模式语义

原 model 指针 `07E:07F=0199`，`model[0]` 为 native mode：0=TTL，1=MAN。

| 位置 | 原生动作 |
|---|---|
| `6A62..6A8C` | 若 banked `081!=0`，强制写 mode=1；否则原 mode==1 写0，其余写1。调用方必须先验证当前 mode∈{0,1}、`081=0`。 |
| `6A8E` | 清 `061`。 |
| `6A90..6A94` | `W=0; CALL AA1C`，将 `029` 置0。 |
| `6A96..6A9E` | `6AF2` 清 `C6:C7`；`A174→8FF8→6B92` 将零输入变成 `FFFF`；`5D30` 存入 `AD:AE`。`AD:AE` 是 MAN 行显示使用的原计时器状态，不能遗漏或误写为0。 |
| `6AA0..6ABA` | 取 `06C..06E` 三字节函数地址，经 PUSH/TOS/RETURN 调用当前组的 mode-rebind 回调，更新 `069..06B`。 |
| `6ABC..6AC4` | `5666` 读 mode；MAN 直接尾跳 `9A48`。 |
| `6AC6` | TTL 调 `7B14`，收集 `19D..19F`，尾跳 `85EA`；后者受 `02A` 抑制。未抑制时会构造 `25`、经 `4AD6/7108/A9D6/A76A` 入无线队列。 |
| `6ACA..6AE8` | TTL 目标下，若 `model[2]=19B==2`，改为3；其余值不改。最终尾跳 `9A48`。 |
| `9A48` | 更新 `08A..094` LCD flags；调用 `7D28` mode glyph、`84A6` group icons、`7E5A` sync glyph、`6C24` 三行、尾跳 `8722` model icons。此链无额外 RF。 |

零计时器到 FFFF 的证据：`6BA6..6BB0` 检查 `C2|C3`，为0时 `SETF BE; SETF BF; RETURN`；`A18C..A190` 回写 `C6:C7`；`5D30` 回写 `AD:AE`。MAN 的 `876E..87B8` 使用 `AD:AE` 决定数字/空行，所以这不是可忽略的 scratch。

`609A(W=group)` 是合法 callback 初始化/组选择入口；group 仅接受1、2、3、7。**不能只写060**。四个 `06C` 回调由其原生分支确定：

| group | `06C..06E` 回调 | TTL `069..06B` | MAN `069..06B` |
|---|---:|---:|---:|
| A=1 | `009B54` | `008A4C` | `0090AE` |
| B=2 | `009B28` | `00814E` | `009072` |
| C=3 | `009AFC` | `008BAA` | `009036` |
| ALL=7 | `009B80` | `00ABC0` | `006930` |

这些回调只根据 `5666` 返回值重绑指针；`ABC0` 是 RETURN。调用 `609A` 时应令 BSR=0；它也维护 `063..068` 并刷新选择图标。

## 对 shared core 的准确调用契约

新 core 的 TTL 投影到 native0；A1、A2 都投影到 native1。A1/A2 的区分、绝对值与相对值、最后模式必须保存在新 core/journal；原 native record 只有1bit mode，不可能独自恢复三种新模式。

1. 在修改原生 RAM 之前验证请求、native mode、`07E:07F=0199`、合法 group，以及调用方的 UI/相机/队列门。`02A` 必须原本为0。要拒绝的分支全部在此完成。
2. 用 `609A` 设置合法组/回调。临时设置 `02A=1`；如果新 native mode 不同，调用原 `6A62`；相同则不 toggle。`081=0` 前置条件保证 toggle 等价于请求的目标。必要字段/FEC/head/model 投影和最终 redraw 由 adapter 原流程完成。
3. 不恢复 `061/029/069..06B/AD:AE/19B` 的旧值；它们是原模式转换的有意副作用。不要用大块 scratch 快照恢复覆盖 IRQ 共享字段。
4. 在这段同步、已闭合调用内归还 `02A=0`。不要调用 scheduler、`888C`、`9F66` 或未闭合函数指针；不要假设 `02A` 是跨任意异步任务的通用 mutex。
5. **仅 boot MODE projection** 成功时，按最终 mode 重算 `085=(native_mode==0)`；TTL=1，A1/A2=0。与 parent 确认的 ABI 中 MODE bit1 只出现在 boot projection literal9（含 deferred retry），运行时普通 commit 为2/4/8，因此不应在普通字段 apply 时重新置 pending。

第5步是必要的原启动语义：`5520` 在 `558C..5594` 按从 NVM 读出的 mode 初始化 `085`；主循环 `5946` 调 `ABB0`，就绪后在 `5950..5960` 检查085、调用7B14、清085。`6A62` 自身不清085。若 oldTTL→MAN 而保留85，会晚发一帧25；若 oldMAN→TTL 而一直维持85=0，会丢失启动 TTL 同步。boot 成功后重算85使 TTL 使用**恢复后的 FEC**在原就绪条件下发一次，MAN 不发。`apply` 当次仍零 enqueue；core.init 本身不发包，故无重复发送。

若未来 core 改为自行接管首次 TTL 发射，可在 `02A=1` 下调用原 `5950` 消费旧 pending，但这是不同策略；本契约当前推荐保留原启动 pending 发射，不消费 TTL 的85。

## 原 NVM 怎样恢复 mode

`5796 CALL 5E1C` 在 `57AA CALL 5520` 之前。`5E1C` 建 `1AB` flash journal descriptor，`5EB0 CALL6166` 读取记录，`5EC4 CALL A66C` 把记录解包到 model0199。链为 `A66C→A684→7CC0` 载入位域容器，再 `9590→5FC8(A218)` 提取位域，`6230(A542)` 写 model。**此恢复链不调用6A62**；随后5520才建立 native timers、07E指针、组回调、LCD和085。

`6230` 映射顺序是 model+4、+5、+6、+0、+2；前三项经过20偏移，mode不偏移。`5FC8` 的字段 offset/width 为 `(0,6),(6,6),(12,6),(18,1),(19,2)`。因此原 journal 仅保存三组FEC、1bit native mode、2bit sync，不保存新A1/A2区别。正常记录区见 `ram_nvm_contract.json`：`1F800..1FBFF`，不得与新的 journal 混用。

VM 原生 pack/unpack 的 FEC=(-20,0,20),sync=2 样例：mode0记录`00 0a e5 ff`；mode1记录`00 0a ed ff`；解包恢复 mode/FEC/sync，未进入6A62，也无外设事件。原生启动应先完成，再用新 journal 的最后TTL/A1/A2投影；切勿在5520之前调用依赖06C/07E的mode body。

## `02A` 的静态闭包证明

从 `4108` 穷尽直接 CALL/RCALL/GOTO/BRA、全部条件跳转和双 skip 边：392条指令，所有目标已解码，0个PUSH/TOS间接派发。直接 file/MOVFF 操作中没有02A读写。IRQ 的间接数据指针均可回溯：

- `4152..415E` 传 state pointer0040给67E8；它读写0040。
- `A8EC` 置 `001:002=01B2`；719A 的FSR1/2为descriptor+0/+2/+3/+4等。719C的 `LFSR1,2` 是offset，随后加01B2成为01B4。
- ring buffer 由原 `678A..67A0→8FBA` 初始化为0215、长度50；原指针不变量下，IRQ只写0215..0246。descriptor itself为01B2..01B7。
- packet buffer 为0247+8bit089，正常最多026E；即使只用8bit索引上界也不可能到002A（上界0346）。IRQ直写0247/0248及019A、计时器B1:B2/B5:B6。
- IRQ FSR1/2保存于01A..01D并恢复；无FSR0/TBLPTR/PROD修改。

所以已恢复应用的此 IRQ 路径不会在临时 inhibit 期间把02A改成新事件，归还0不会覆盖IRQ写入。这个结论以原ring指针、无RAM损坏为前提，不等于所有bootloader/未知异常路径证明。

模式闭包用已知条件 `02A=1` 固定85EE的提前返回边，用 `6AF2` 的零输入固定6BAA边，并加入上述四个06C回调：866条指令，唯一02A消费者是85EC，无02A写。唯一PUSH为6AA8，四个目标已闭合。完整指令地址和direct callee列表保存在JSON，测试重建并检查392/866及唯一消费者。普通分支最终经9A48/8722返回，不清02A、不进入其它radio consumers。

全 listing 的真实直接02A读：`6CB6,708A,809A,85EC,8976,89BE,9F66,A60C,A72C,A76A`；直接清除：`888C,9F6C`（另有startup clear覆盖02A）。这些清除不在模式或IRQ闭包。4232的“INCF02A”是ASCII字符串`***`的伪解码，不是可执行写。没有找到普通应用非零直接写，但这里不声称所有generic pointer路径都不会访问02A。

## 相机与临时强制MAN的保守门

原82==0/A838非零只证明原正常UI条件；02A==0只证明radio-inhibit没置位。不能把它们单独称为camera idle。

| 条件/字段 | 可验证证据及含义 |
|---|---|
| `040==1` | 8D3E初始化、9CAC reset最终经8D6C写1。IRQ收到55首字节写2，第二字节写3，main4FEA分派3/4/5/8进入parse/收包/reset；1是明确RX等待态。 |
| `089==0` | RX cursor；8D4C/9CCE及67E8高select分支清0，首/次字节分别写1/2。仅state1不足以表明无待处理电气输入。 |
| `F81.2==1` | 67EC看到高电平走686C，清89并重置state1；低电平走收包。是原物理非选中条件，不等同bankedRAM081。 |
| `19A==0` | IRQ4122检查phase1，AB38发pulse后清19A并设B1计时；其它phase写3。main4E22..4E42处理B1超时再清19A。非零应视为sync/phase有事待处理。 |
| `081==0 && 02D==0` | camera parser466A..4684根据packet+8低7bit==8调用8A92(1)：设置081并armA1 timer。75AC检测后若TTL则设2D、arm9F timer、6A62强制MAN。8A92(0)若2D非零则调用6A62恢复TTL。投影持久模式不能夹在这条临时模式往返中。 |

建议 conservative software gate 合取：原 `082==0`、`CALL A838 !=0`（signed24:25≥3）、`02A==0`、TX count097==0、上述040/089/081/02D/019A条件。提交新RF记录前还应在短关IRQ窗口复查该门和 IRQ pending：`FF0.1`、`F9E.5`、`FA4.5`（保守要求均0，或者与原enable位FF0.4/F9D.5/FA3.5配对）。保留并恢复进入前IRQ状态，不能使用原flash helper那种无条件enable策略。

这些是从原路径获得的**保守门**，不是所有拍摄电气状态的完成证明。物理事件可以在采样后到来；原6A62也并不关闭IRQ。因此避免跨整个LCD/mode调用长时间关IRQ，队列发布另做短原子事务，并在真正发射前重新检查。不要照搬S的D8/56/48/194字段或F的0FE字段。O的IRQ共享范围见RAM契约；不能用全scratch保存/恢复去抹掉新事件。

## 验证与边界

运行：`python analysis/air_remote_ttl_multi_air2/O/test_mode_transition.py`。4项测试全部通过：96组原mode/timer/callback矩阵；392IRQ/866mode闭包；6组boot旧mode×TTL/A1/A2投影及原pending一次性发射；原NVM mode0/1 pack/unpack。96组中最大931条VM指令，发送ring descriptor095..09A与buffer300..363逐字节不变，无外设事件；TTL目标会进入85EA但不进入7112/9F1E/7108/A76A。

## NV 提交前实时门控补充 / Live pre-commit NV gate

原 IRQ `411A..413E` 消费 `FF0.1`，`4140..4148` 检查 `F9E.5` 后读取接收数据，
`414C..4162` 消费 `FA4.5` 并调用 `67E8`。因此，`040==1` / `19A==0`
只反映已处理事件；中断屏蔽后仍可能存在尚未执行 ISR 的 pending 位。
旧实现实际指令反例：分别置这三个 pending 位而保留缓存空闲，`read_inputs`
均返回 `87`，错误地允许 NV 提交。

现仅在 NV-ready 位 2 设置前增加只读条件：`089==0`、`F81.2==1`，
`FF0.1` / `F9E.5` / `FA4.5` 均为 0。物理选择信号极性由 `67EC` 高电平进入
`686C`、清 cursor089 并恢复空闲状态确认。检查不依赖 IRQ enable 位、不清 pending、
不读取会消费接收数据的寄存器。shared NV 在每次擦除/字写之前屏蔽 IRQ 后重新调用
该入口，避免拿较早的缓存空闲授权写入。编辑、射频和原 HSS/ISR 指令未修改。

The native ISR consumes `FF0.1`, `F9E.5` and `FA4.5`; cached camera state alone
cannot exclude an interrupt that is already pending when interrupts are masked.
The NV-ready path now reads the pending flags and physical deselection signal
directly, and requires cursor089 to be zero. It leaves flags and receiver data
untouched. The shared NV implementation repeats this check with interrupts
masked before each erase or word write. Original edit/radio behavior and HSS/ISR
instructions remain unchanged. This addresses already-pending inputs; it does
not claim that future asynchronous edges cannot arrive after a sample.

`test_nv_fresh_gate.py` 执行真实链接核心、O backend 和 shared NV 指令：空闲记录
16 次字写成功；5 个忙条件 × 4 种原 IRQ 状态均拒绝，程序内存与标志不变、原 IRQ
状态恢复；三个 pending 位分别在较早快照通过后、masked recheck 时注入，均零擦写。
唯一外设模型是 flash 操作的存储效果和 pending 到达，没有替换 native helper。

The regression executes actual linked machine code: an idle commit succeeds,
20 combinations of busy inputs and initial IRQ states perform no flash writes,
and all three pending flags injected during the masked recheck are refused.
Flags remain set and the original IRQ state is restored. Peripheral memory
effects and flag arrival are explicit test boundaries; native helpers are not
replaced.

VM不是电气时序或自动IRQ抢占仿真。原未知首word4000、bootloader、其它异常入口和真实相机兼容性未因此得到证明。直接/间接 pointer 不变量和 preimage 必须随目标固件保持；不匹配时该契约不可复用。
