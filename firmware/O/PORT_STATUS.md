# Olympus TTL-O A4 AIR2 adapter / Olympus 移植状态

Developer / 开发者：**Caimankekw**. Authored source / 自编代码：**AGPL-3.0-only**.

This directory implements the Olympus A4 native adapter for the shared AIR2
core. It does not import the Canon HSS-P3 baseline. Original Olympus camera,
HSS and radio implementations are retained; six checked UI/startup call sites
connect the new policy. Hardware boot, camera operation and RF reception have
not been tested on an Olympus unit.

本目录实现 Olympus A4 对共享 AIR2 核心的适配，未导入 Canon HSS-P3。
保留 Olympus 原相机、HSS、无线实现，只修改六处已核对的 UI／启动入口。
尚未进行 Olympus 实机开机、相机和无线接收验证。

## Implementation / 实现

- `model_adapter.py`: two-pass, in-memory composition / 两遍链接，仅读写内存。
- `native_backend.py`: original LCD, native 16-byte TX queue, input snapshots,
  native state projection and native MODE restoration / 原 LCD、16 字节发送队列、
  输入快照、状态映射和原生 MODE 恢复。
- `native_hooks.py`: six exact preimages; original caller context and return
  flow / 六处精确原始字节；保存原调用上下文及返回流程。
- `port_profile.json`: explicit target mappings and bounded evidence / 型号地址、
  内存和有限正常路径的证据；最终发布资格由根构建器绑定校验结果。
- Shared `persistence_backend.py`: new V5 two-page journal at F800/FC00.
  The original journal at 1F800..1FBFF is preserved / 新 V5 日志使用 F800、FC00，
  保留原 1F800..1FBFF 设置区。

The backend's local `nv_load`/`nv_commit` refusing entries are fallback exports.
The complete linker explicitly replaces their imports with the qualified shared
NVM implementation. They are not used as a substitute for persistence.

backend 内的 NVM 拒绝入口仅为独立测试的退路；完整链接将其替换为已启用的
共享 NVM 实现，并检查证明状态，不能把空入口视为已完成记忆功能。

## UI behavior / 界面行为

- C + HEAD changes ABC/DEF pages; C + MODEL changes AIR1/AIR2 in MAN.
  Normal A/B and power +/- do not enter the chord delay / C＋HEAD 翻页，
  MAN 下 C＋MODEL 切换 AIR1/AIR2；A/B 和加减键不进入组合键等待。
- AIR2 shows all three absolute targets. AIR1 relative values expire through
  the original AD:AE idle timer, including TTL/DEF AIR1 / AIR2 三组绝对值常驻；
  AIR1 使用原 AD:AE 计时器隐藏相对值，包含 TTL 下 DEF 的 AIR1 页面。
- Page changes briefly display A/B/C or d/E/F, then restore values. Fixed ABC
  glass labels are hidden on DEF / 翻页短暂显示 A/B/C 或 d/E/F，然后恢复数值；
  DEF 隐藏液晶固定 ABC 标签。
- Native ABC camera fields always retain ABC meaning; DEF display does not
  overwrite them / 原 ABC 相机字段始终表示 ABC，不借其存放 DEF 页面状态。
- Last mode, AIR2 targets and switch state use shared V5 records. A restored
  TTL mode maintains the original deferred startup command 25, without an
  immediate duplicate frame from the new apply helper / 共享 V5 记录保存模式、
  AIR2 功率和开关；恢复 TTL 时保留原启动延后 25 指令，不由新映射函数重复入队。

## Verification / 校验

Run from the workspace root / 从工作区根目录运行：

```powershell
python -X utf8 -B -m unittest discover -s analysis/air_remote_ttl_multi_air2/O -p 'test_*.py' -v
```

The local suite passed 31 tests, including 600 original numeric LCD cases,
101 BCD cases, 96 native MODE combinations, native queue capacity/wrap cases,
real shared-core key hooks, context preservation, page hints and original idle
timer handling. Original helper calls execute their actual instructions, with
no helper replacement in these tests. The shared integration suite separately
checks linked firmware and persistent reboot scenarios.

本地 31 项测试通过，包含 600 个原数值显示案例、101 个 BCD 案例、96 个原 MODE
组合、原队列容量／环绕、实际共享核心按键入口、上下文保存、分页提示和原计时器。
这些测试执行原 helper 的真实指令，不用替代 helper。共享集成测试另行验证完整
链接固件和记忆后的重启场景。

Static/VM validation does not establish physical timing, radio acknowledgement,
or hardware reliability. The runtime checks preserve native camera/queue gates
and reject edits or saves when the original state is busy or unknown.

静态与指令回放不能证明物理时序、无线执行回执或硬件可靠性。运行时继续遵守原
相机和队列门控；原状态忙或未确认时拒绝修改和保存。
