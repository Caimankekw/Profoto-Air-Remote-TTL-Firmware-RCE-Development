# Sony A6 原生队列、相机状态与短提交审计

[English](CONCURRENCY.md)

输入是本目录上一级 `shared_codec_candidate.base4000.bin`，SHA256 为
`b5d7c9b199cc1a705514c028d609e31bb8b6fb55813cdc2ab1fcba898be7cee5`。
本文不修改原HSS，不执行更新器、USB或硬件测试。

## 已确认的状态

| 位置 | 证据及含义 | 能否证明HSS空闲 |
|---|---|---|
| RAM `0D8` | A5A4置1，A906丢弃队列并排入RSUU1；93BC清0并排入RSUU0 | 原radio独占门，不覆盖全部相机阶段 |
| RAM `0DD` | 原厂诊断UI状态；6D54/6DB4按1/2/3/5/6/7显示HELLO/A6/rAdio/G I t/bb178/全段 | 不能；0仅适合允许普通UI编辑 |
| RAM `0DC` | 9D5E写临时模式锁，78B4在非零时强制camera[0]=1，9708到期清除 | 不能；明确setter调用6C0E/A028均传0，未恢复DC=1活路径 |
| RAM `0193` | 主4E72..4E7A通过5068把D2/D3绑定到0193；9690读取object[0]模式 | 是模式，不是同步阶段 |
| RAM `0194` | camera object[1]；ISR使用0/1接收，2等待同步释放，3另一预备路径，4/5完成处理 | 只能筛除已知活动阶段，不是RF完成回执 |
| RAM `0056` | 相机握手状态；6E68处理0..5，通常恢复1；2/4由ISR收数据 | 不可单独作为HSS完成条件 |
| RAM `0048` | ISR完成后置1，main4EB2..4EBA调用93BC退出radio独占并清除 | 尚待前台处理的完成事件 |

`0194=5`由ISR41BE/41F0设置，主6BB0处理超时时特意保留5；只允许0194=0会拒绝已完成后的正常操作。80F2调用的AB0C仅判断有符号D1:D0是否>=3，并非HSS忙检查。87CC使用CA/CB/CC间接加减回调，没有队列事务锁。

## ISR确实会修改同一队列

真实ISR入口为4108，4250为RETFIE 1。41B8是41B6的CALL 8C00的续字，不能作为独立ISR入口。

生产者路径：414E→7842→78B0→5B34→5BE8→5858→589A→7D9E→90BA→AC84→7002。进入414E要求0194=0且56=1；5B34允许361..449计时单位的识别区间；3E/3F=025F且packet[7].7=1、packet[10].7=0进入589A。这条路径会形成RSUTP文本记录。5858的其他分支经A814→A5A4→A906丢弃同一E6队列并写RSUU1。不能把D8检查视为完整互斥。

`static_isr_audit.py`保留所有条件分支，遍历4108直接控制流闭包1711个地址，无未知解码、PUSH或其它识别出的间接控制点；90BA/AC84/A906/7002可达，5C08/5DA4/7296不可达。原消费者5DA4只有5C6C一个直接调用点，5C08仅由A586进入，A586仅在main4EA0/4EBC调用。新提交必须保持在前台、这些服务和queue helper之外，不能从消费者回调中重入。

`audit_concurrency.py`重放原17B入队，在marker后调度真实90BA，然后继续真实86EA。初始count0时，ASCII记录插入frame中间；count83时最后数个frame字节被满队列拒绝，而调用者仍返回1。400例周期统计中，A158耗2065–2105指令周期，高RAM长wrapper耗2259–2299周期，不能把整段包装成短临界区。

## 可供整合的242字节候选

`fast_empty_queue.construct(base, frame_ram, irq_ram)`由整合者指定代码和17字节自有RAM。它不产生hook、整机镜像或可刷写包。

1. 前台预检ISR-active位、D8=0、E8=count=0、56=1、48=0、194为0或5；相机pending FF0.0/.1、F98.4、FA4.7必须为0；核对原capacity100/data0400布局。
2. 保存原GIEH/GIEL，只清这两个位。临界区内再次检查上述运行态。
3. 固定写400的零marker和401..410的16字节frame，设read=0、write=17，最后写count=17。原空队列索引可非零，前台消费者在此期间不能运行或重入。
4. 仅逐位恢复原GIEL/GIEH，保留实时IF及其它INTCON位，IPEN始终不变。

W=1表示本地记录已准入，W=0表示本次未提交。失败不会改队列描述符或数据；允许改自有irq暂存、W/STATUS/BSR。恢复中断之后原A5A4可以合法丢弃刚接受的帧；这个abort必须保持权威，禁止辅助函数无条件重发旧域目标。

这套门控只证明观察到的软件状态处于允许集合，不保证全物理HSS已结束。最后一次pending检查之后到达的中断仍会等待临界区结束。最长74指令周期，物理时间为74/F_instruction秒；本审计未确定晶振、PLL、硬件同步延迟或空口时延。

## 离线验证

`python -B analysis/air_remote_ttl_multi_air2/S/radio/test_fast_empty_queue.py`

共享PIC18 VM共2555例通过：1600个空环位置/0与5状态/GIE位/IPEN矩阵；23个拒绝条件；740个成功路径指令边界，分别调度原90BA append与A5A4 abort。包含旧read/write=93、恢复前后新增IF、postcommit abort、原5DA4后续序列化。

调度的是完整原生产者函数，未stub其入队/清空逻辑；中断优先级、硬件采样和完整4108 ISR未被模拟。因此这是明确边界的线性化验证，不是硬件HSS等价证明。独立审核另在shared/HSS_PRESERVATION_REVIEW.json保存44例结果。
