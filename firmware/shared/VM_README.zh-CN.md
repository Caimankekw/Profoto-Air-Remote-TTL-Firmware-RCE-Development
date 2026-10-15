# PIC18 有界原码回放器

开发者：Caimankekw。源码按 `AGPL-3.0-only` 提供。

`pic18_vm.py` 是标准库实现的经典 PIC18 指令回放器，供 N C5、S A6、F A5、O A4 的离线移植验证共同使用。它不连接 USB，不运行更新器，也不提供默认成功的硬件或原函数替代。

## 运行验证

在仓库根目录执行：

```powershell
python analysis/air_remote_ttl_multi_air2/shared/test_pic18_vm.py
python -O analysis/air_remote_ttl_multi_air2/shared/test_pic18_vm.py
```

输出 JSON 报告，包含检查数、VM／测试源码 SHA-256、四份原始镜像 SHA-256、已知字节掩码 SHA-256。测试不写报告或固件文件。检查使用显式异常，`-O` 不会移除验收条件。

当前覆盖 408,236 个有界案例：

| 范围 | 数量 | 验证内容 |
|---|---:|---|
| 带进位／借位算术 | 393,216 | ADDWFC、SUBWFB、SUBFWB 的全部两字节输入及旧 C，比较结果和 C/DC/Z/OV/N |
| INCF／DECF | 512 | 全部字节及五个算术标志 |
| DAW | 10,000 | 所有两个 0–99 BCD 数相加后的调整结果和进位 |
| 寻址、控制流和拒绝条件 | 346 | 三个 FSR 的索引和 RMW、虚拟间接目标、MOVFF、STATUS 目的写入、MOVLB 全 literal、PCL、返回栈、FAST、跳过双字指令、22 位 TBLPTR、外设显式边界 |
| N／S／F 按键历史 | 3,072 | 每款 256 个旧值 × 4 种布尔输入，实际执行原程序 |
| N／F BCD、S 模式、F 限幅／指针／字形 | 480 | 直接执行原辅助函数，无函数替代 |
| O 显示格式化 | 600 | 三行各 -99…100，执行原字形表与显示辅助函数 |
| N／F 队列及 N 帧构造 | 10 | 队列容量边界、环回、真实 RSGT1 帧和源数据保留 |

以上原码案例不使用 `step_hooks` 或外设钩子；通过不代表完整应用、无线模块、相机、LCD 或硬件 Flash 已实测。

## 接口

```python
from pathlib import Path
from pic18_vm import CPU

p = Path("analysis/air_remote_ttl_multi_air2/shared/stock/O")
cpu = CPU(
    (p / "original.base4000.partial.bin").read_bytes(),
    values={0xB7: 0x8A, 0xB8: 0x8B, 0xB9: 1},
    mask=(p / "original.known_mask.bin").read_bytes(),
)
cpu.run(0x742E, max_steps=10000)
print(cpu.m[0x8A:0x8D])  # C0 EF 60
```

主要成员：

- `CPU(image, values=None, mask=None, base=0x4000, flash=None, xinst=False, ...)`。`image` 是该地址起始的代码；`mask` 与代码等长，零表示未恢复字节。使用已提供固件时应始终传入已知掩码。
- `m` 是 4096 字节逻辑数据空间，`w` 与 `m[0xFE8]` 一致；`get_fsr(i)`／`set_fsr(i, address)` 操作 FSR0/1/2。
- `run(entry, stops=(), max_steps=None)` 执行真实 CALL/RCALL，至顶层 RETURN/RETLW 或指定停止地址；默认每次最多 800,000 步。超限抛 `StepLimit`，不算成功。
- `pc`、`stack`、`steps`、`reads`、`writes`、`events` 可检查执行；`track_trace=True` 时记录 `trace`。`steps` 是累计执行指令数，不是周期数。
- `decode(pc)` 返回指令记录；`code`、`mask`、解码缓存假定执行期间代码不变。Flash 自编程测试若修改将要执行的代码，需要调用方明确同步 `code` 并清除解码缓存。

`values` 是调用方给出的初始状态，不表示实机采样。直接写 `m` 是测试设置；它不触发写钩子或模拟外设。

## 外设及替代边界

默认 `strict_peripherals=True`。除了明确实现的 CPU 架构寄存器，未提供的 SFR 访问抛 `PeripheralBoundary`。可以逐地址设置：

```python
cpu.read_hooks[0xFAD] = lambda c: 0x02

def tx_write(c, value):
    c.m[0xFAE] = value
    # 调用方在此记录或解释发出的字节。

cpu.write_hooks[0xFAE] = tx_write
```

读钩子必须返回一个字节；写钩子负责其完整副作用，包括是否更新 `m`。每次调用都会加入 `events`。`allowed_sfr={...}` 或在 `values` 中给出 SFR 只建立静态寄存器边界，不会自动模拟 ready、计时、收发中断或写入完成。关闭严格检查必须在使用者报告中明确说明。

`step_hooks[address] = fn(cpu)` 会替代该地址的整个函数并模拟返回，事件标为 `step_hook`。这仅适用于明确声明的有界测试；经过替代函数的路径不能声称该函数原码已执行。VM 本身没有预置任何原厂函数替代。

Flash 使用绝对地址 `flash`／`flash_mask`。未传入完整 Flash 时，仅镜像中已知字节被标记为已知，其他填充值不能当成已读取数据。显式传入 `flash` 而省略 `flash_mask` 表示调用方声明整份模拟 Flash 都已知。

TBLRD 执行真实表指针寻址，并检查已知掩码；表指针为 22 位，自动增减仅改变低 21 位并保留 bit21。TBLWT 只记录 `latches`，不提交擦写。没有默认的 EECON 解锁、页擦除或写入控制器。需要这些行为的测试须在受限地址范围内自行提供 SFR 模型，并区分软件断电模型与真实器件行为。这里没有继承 C11 的 NVM 页地址或可写范围假设。

## 指令规则和明确限制

实现经典 ACCESS／BSR 寻址、三套 FSR 的 INDF／PLUSW／PREINC／POSTINC／POSTDEC、双字指令、算术和条件分支、乘法、DAW、表读写、PUSH／POP／TOS、PCL 计算转移，以及单个全局 FAST shadow。PLUSW 使用有符号 W；一次 RMW 只解析一次有效地址并推进一次指针。带跳过的增减不修改算术标志；影响标志且以 STATUS 为目的的指令保留未受影响标志，例如 `CLRF STATUS` 只设置 Z。STATUS 高三位按未实现位处理。

虚拟间接寄存器指向另一虚拟间接寄存器时读零、写入忽略。自动索引操作同时别名到自身 FSR 寄存器的特殊情况暂时明确拒绝，没有推测冲突优先级。MOVFF 目的为 PCL／TOS 时按指令限制拒绝。

- `XINST=True`、RESET、SLEEP、RETFIE、未实现或非法操作码、未知代码、未知表字节均拒绝。
- 不注入中断，不模拟异步 UART／SPI、计时器、看门狗复位或电气状态。CLRWDT 仅记录事件。
- 硬件返回栈最大 31 层；溢出、POP 下溢、无已知上下文的 FAST 恢复等拒绝。顶层 RETURN 表示测试函数正常结束。
- `0xFFFF` 视为擦除区而拒绝执行；已知 `0xF000…0xFFFE` 在经典指令配置下可作为续字 NOP，调用方可用 `allow_continuation_nop=False` 禁止。
- 数据空间大小是逻辑寻址模型，不能据此证明具体芯片实现了所有 RAM 或某块 RAM 可供新模块使用。经典指令配置也不是对四款产品精确 MCU／XINST 熔丝的鉴定。
- 不估算循环耗时，不证明峰值 ISR 栈深、异步竞争、Flash 磨损／电压／掉电原子性、协议 ACK 或实机 HSS 行为。

指令语义依据 Microchip [PIC18F47J53 系列数据手册 DS30009964C](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/30009964C.pdf) 中的经典 PIC18 指令定义及返回栈／间接寻址章节（印刷页 78–80、99–100、466、472、476–482 等）。该参考用于 CPU 指令语义，不作为四个固件精确芯片身份的结论。

## 原码回放纠正的 ABI 信息

富士 A5 的 `0x96D0` 有符号限幅入口，B0:B1 是目标指针，**B2 是上界、B3 是下界**。Nikon `0x9D54` 和 Fuji `0xA60A` 所用环队列对象前两个字段依次是 **write index、read index**，随后为 count、capacity、buffer pointer。测试绑定实际镜像及真实调用链，不沿用旧口头参数推断。
