# Air Remote TTL-F A5：AIR2 移植证据与本机桥接代码

此目录包含离线开发源码与证据，安装包由共享发行流程单独输出。使用 Fujifilm A5 本机程序作为基线，未引用 Canon HSS-P3，也未修改 Fujifilm 原有 HSS 或热靴处理代码。M2 的期限、ALL 选框及忙状态重试修复见 [M2 UI 修复](M2_UI_FIX.zh-CN.md)。

## 已确认

- A5 使用与 Nikon／Olympus 系列相近的对象式 PIC18 ABI；Canon C11 的函数地址、静态 RAM、键盘和液晶调用约定均不能原样复用。
- 原应用结束于 `0xB2E0`；共享解码器回环和原容器 CRC 已通过，首两个未知字节由共享封包器原样保留。
- 原厂 12 个按键对象位于 `0x010A..0x0139`，每对象四字节。`C/MODEL/HEAD` 为 `0x011E/0x0122/0x0126`，`+/-` 为 `0x012A/0x012E`。原始扫描由 `0x48EA` 完成；`0xA50E` 每次轮询一个对象，`0x581A` 产生按下、释放和长按事件。
- 正常页按键入口为 `0x5E6A`；加减释放和长按分别由 `0x8D34` 与 `0x70E6` 进入 `0x8D7E`，传入 `±1/±10`。新组合键不需要让加减键进入第二套等待窗口。
- 原厂无线类型函数 `0xB2CE` 恒返回 `2`，走 `RSGT1`、16 字节包体。`0xA60A` 通过原 TX ring 写入一个标记字节及包体，保留原无线调度。TX 描述符 `0x92`、缓冲 `0x500`、容量 100，描述符偏移依次是写索引、读索引、计数、容量、缓冲地址。
- 新桥接的 `enqueue_preflight` 按 17 字节检查空间，遵守原 `0x9562` 严格 `<100` 条件；因此计数 82 可接受，83 拒绝。测试不把原包体 16 字节误当成整条队列记录。
- 原 `0x7AD2` 液晶格式化器可显示 `0.1..9.9` 和 `10` 端点；绝对功率模式调用原符号函数清除正负号即可。空白与 Head OFF 分别使用 `0xAFE4/0xAFD4`。

## 文件与验证

- `F_A5_adapter_evidence.json`：确定的函数、按键、状态字段、回调地址和原码 preimage；由 `build_evidence.py` 重建，当前 14 项静态检查。
- `native_backend.py`：参数化的原机桥接汇编生成器。包括真实 RAM 快照、按键原始状态、非阻塞队列预检、原模式回调和各行显示。默认不启用发射准入；正式联结必须提供原接口和准入证明。
- `native_hooks.py`：八处完整指令边界上的启动、服务、正常页按键、功率、显示及原闲置期限 hook，包含 TTL DEF AIR1 原生模式 gate 扩展。原 HSS 路径不接入新逻辑。
- `test_native_backend.py`：将新桥接与**原 A5 机器码**一起回放，未用 helper stub 替代原函数；验证 10 类场景，包括队列边界、各种忙门、各行 0.1 至 10.0、负数、空白、关闭显示、原模式回调、IRQ 字段保护和旧快照拒绝。
- `native_backend_test_report.json`：上述回放结果。VM 的 `0x680` 仅是测试地址，不能单独证明设备 RAM 可分配。
- `test_integrated_hooks.py` 与 `integrated_hooks_test_report.json`：原 stock＋共享策略 core＋本型号 backend＋八处 hook 的内存联结回放，目前 7 类通过；不生成 HEX 或 EXE。包含真实原入口加功率、完整 AIR2 包、原按键、显示无递归、AIR1 消隐和 DEF 显示隔离。
- `test_ui_parity_m2.py`：102 项 M2 整合回归，从真实上游闲置与 LCD 入口检查模式矩阵、ALL、期限回绕和忙状态重试。可用 `--out` 生成 JSON 报告。
- `audit_clock_irq.py` 与 `F_A5_clock_irq_evidence.json`：完整 IRQ 控制流、原 tick 分频、原射频抑制与唤醒状态、ISR 写字段及 NVM 寄存器审计。
- `port_profile.json`：供共享构建器使用的 F A5 独立映射、384 字节 RAM 分配、原生计时域、准入门、持久化几何及受保护原码范围。最终验证状态由整包构建器绑定，不能由该配置自证。
- `c11_codec_candidate.listing.txt`：离线线性指令列表，其中也会把常量当候选指令，不能凭列表项存在就判定其可执行。
- `function_candidates.json`、`tentative_whole_alignment.json`、`nf_alignment.json` 是探索性匹配，不是可刷补丁地址的依据。

运行：

```powershell
python -X utf8 -B analysis/air_remote_ttl_multi_air2/F/build_evidence.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/F/test_native_backend.py
python -X utf8 -B analysis/air_remote_ttl_multi_air2/F/test_integrated_hooks.py
```

## 集成时仍需闭合

共享硬件与 RAM 审计支持在原对象正常、索引合法的工程模型下使用 `0x680..0x7FF`，且保留 F 的 `0x600..0x67F` 不动；依据见 `shared/identity_report.json` 与 `shared/ram_allocation_audit.json`。这一有边界审计不替代设备实际内存测试，也不是仅由初始化上界作出的推断。

新无线包只应在原 camera idle、正常页面、原待发送状态为空且无相机待处理中断时准入。`enable_admission=True` 实现了保守候选门：`RAM7A/28/61/85/94 == 0`、`RAM3A == 1`、`FA4.bit7 == 0`、`FF0.bits1..2 == 0`。独立 IRQ 审计证明 ISR 不生产 TX ring，只生产 RX ring；这允许保留中断抢占，避免通过长时间关中断影响 HSS。准入检查不能保证未来不会立即发生相机中断，亦不是无线或灯具执行确认。

外层 hook、原调用者 scratch 保存、六组显示与页提示、camera ABC 状态和 DEF 显示隔离、原模式回调已联结回放。必须保留 **RAM0FE** 的 ISR 写入：`4150→83B4→AE22` 在中断中发布相机命令，整体保存／恢复 `B0..FF` 会覆盖新事件；本版本明确排除 `0FE/2B1/1DA/1E0`。

ABC／DEF 切换时显示一次 `A/b/C` 或 `d/E/F` 字符提示，下一次重绘恢复数值；DEF 隐去固定 ABC 字样。该提示采用动作触发，不另造计时器。DEF 的 Head/model 图标从规范六组状态绘到 LCD，原相机的 ABC 掩码保持 ABC。

本机 `nv_load/nv_commit` 是供共享持久化组件覆盖的禁用桩。最终联结应使用 `shared/persistence_backend.py`，并提供真实 `read_inputs` 与硬件、RAM、空白页、ISR 上下文证明。`native_nv_gate_proven=True` 才允许读输入提供 NV bit2；要求原闲置门通过且所有键释放。IRQ 不访问 TBLPTR/TABLAT 或 EECON，原始使能位仍必须由共享 NV 原值恢复。最终启用 NV 的整包回放和实机测试需另行记录。

中文免责声明和许可证沿用项目发行规则；此目录仅为逆向与开发代码，不授权通过静态测试宣称 HSS 实拍表现或可刷包已验证。
