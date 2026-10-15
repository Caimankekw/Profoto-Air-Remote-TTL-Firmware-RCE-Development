# M2 原厂 HSS 保留复核 / Stock HSS preservation review

开发者 / Developer: Caimankekw · AGPL-3.0-only applies to authored work.

M2 四款最终镜像通过有边界的原厂 HSS 保留检查。原中断入口、相机/HSS 关键路径、原生日志、计时器配置和声明保护区保持原字节；新增变化限定在 AIR2/UI 钩子及新增代码区。启动开关恢复和到期清屏不会额外发送射频帧。未采用 Canon HSS-P3 修改。

All four final M2 images passed a bounded stock-HSS preservation review. Original IRQ entries, camera/HSS paths, journal, timer configuration and declared protected ranges retain their bytes. Changes are limited to declared AIR2/UI hooks and new code. Startup mask restoration and idle clearing add no RF frames. Canon HSS-P3 changes are not imported.

验证包含 32 项独立实际指令探针，并与每个最终镜像的普通/优化整合及启动恢复报告绑定。精确镜像、保护区哈希、源报告哈希和边界见 [JSON](HSS_PRESERVATION_M2.json)。完整历史工作区分析不随源码归档；本摘要仅保留必要证据。

The review includes 32 independent actual-instruction probes and binds the final images to normal/optimized integration and boot-restoration reports. The [JSON summary](HSS_PRESERVATION_M2.json) records exact image and protected-range hashes, source-report hash and limits. Full historical workspace analysis is not part of the source archive.

归档检查随后只修改了主机构建工具的默认原厂输入路径：优先读取独立源码的 inputs/ 目录，显式输入仍优先，错误文件仍拒绝。补充复核确认旧、新工具对四个最终计划生成相同的 EXE、HEX 和局部明文，已更新最终报告的工具源码与构建材料指纹。该改动不生成设备指令，详情另记在 JSON 摘要中。

A subsequent archive check changed only the host build tool's default stock-input path to prefer the standalone inputs/ layout. Explicit inputs still win and wrong files still fail. Supplemental review confirms that old and new tools produce identical EXE, HEX and partial images for all four final plans. The final report was rebound to current tool and build hashes. No device instructions change; the JSON summary records the host-tool delta.

这不是物理 HSS/RF 时序一致、零附加延迟、实机开机或曝光通过的证明。新鲜状态检查是快照，不阻止检查后发生相机中断；原计数不推断为校准毫秒；本地入队不是灯端确认。仍需匹配卡口的相机、引闪器和灯具验收。

This does not prove identical physical HSS/RF timing, zero added latency, hardware boot or exposure correctness. Fresh readiness is a snapshot, not an atomic exclusion of subsequent camera IRQs. Native counts are not calibrated milliseconds, and local queue admission is not a lamp acknowledgment. Hardware acceptance remains necessary.
