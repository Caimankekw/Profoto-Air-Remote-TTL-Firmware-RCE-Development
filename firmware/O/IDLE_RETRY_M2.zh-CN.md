# Olympus A4：AIR1 到期重试修复

[English](IDLE_RETRY_M2.md)

开发者：Caimankekw。新增代码采用 AGPL-3.0-only。

M1 的 MAN 原生路径 `7FA0 → 7FBE → 7FC2..7FC8` 及 TTL DEF 的服务包装器，在 AIR1 清除被待发送事务拒绝后，仍调用 `AA38` 将 `AD:AE` 期限清零。相对数字因此没有清除，也失去了后续重试机会。已在冻结 M1 图像中分别复现这两条反例。

M2 将原 `7FBE` 的 CALL 替换为同宽 GOTO 包装器，原生 `6C24` 每次仍只调用一次。已初始化且有可见相对数字的 AIR1 直接执行共享 `idle_expired`；共享代码重新读取原生输入与无线就绪状态。返回 0 时恢复上下文，转到 `7FCC`，保留原生已到期状态；成功时转到 `7FC2`，由原生代码清除期限。A2 等原生消费路径不变。TTL DEF 服务也仅在共享清除成功后调用 `AA38`。原始到期算法、期限值、按键重设期限和 HSS 路径没有修改。

从源码包根目录运行：

```powershell
python -X utf8 -B O/test_idle_retry_m2.py
python -X utf8 -B -O O/test_idle_retry_m2.py --report O/idle_retry_m2_results_optimized.json
```

两种运行方式均通过 23 例：MAN／TTL DEF、待发送／原生忙／相机忙／无线队列忙，普通期限及回绕、解除忙后重试、期限边界、禁用期限、转 A2 和 TTL ABC/FEC 负例。MAN 从 `7FA0` 执行；TTL DEF 执行真实服务包装器及原生 `75AC`，通过原生相机忙输入使待发送事务保持未完成。检查成功后调用原生清期限函数、拒绝时没有调用该函数，以及返回栈没有残留。未使用原生函数或共享函数成功桩。报告由上述命令生成。

如需复现旧缺陷，可额外传入 `--baseline-directory <原M1的build/O目录>`；它是可选的外部输入，源码包不依赖该目录。该目录需含原 M1 的 `profile.json`、`linked_components.json` 和唯一的 `.partial.bin`。

验证边界：这是有限输入下的机器码回放，采用明确的外设状态输入，不模拟物理时钟、异步中断或无线接收结果，不代表实机启动与曝光验证。
