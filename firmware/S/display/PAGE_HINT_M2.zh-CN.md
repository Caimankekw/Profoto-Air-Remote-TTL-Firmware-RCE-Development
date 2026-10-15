# Sony AIR2-P8-M2 翻页提示修复

[English](PAGE_HINT_M2.md)

开发者：Caimankekw。项目新增代码采用 AGPL-3.0-only；原厂代码权利归原权利人。

M1 已生成 `page_hint`，但没有任何页切换路径调用它，因此 C＋HEAD 能切换 ABC／DEF 页，数字区却不出现对应字母提示。M2 在成功提交翻页后调用原有字母渲染器；两键稳定全松后重新绘制当前页的正常内容。该生命周期参考已发布 Canon AIR2-P8 的翻页提示和释放后重绘行为。

Sony `port_profile.json` 启用 `page_hint_on_chord` 与 `release_redraw`。共享核心只在该配置启用时连接这两个回调。不会新增提示计时器；原生重绘可能让提示提前结束，稳定全松后的重绘则保证提示不会持续占用功率数字区。AIR1 恢复原有临时数值或空白，AIR2 恢复三个绝对功率，TTL 的 ABC 页恢复曝光补偿。

验证脚本：`test_page_hint_integration.py`。在实际链接的机器码上通过 32 个翻页组合和 4 个负例，覆盖 C／HEAD 两种先按顺序、TTL／MAN、AIR1／AIR2、ABC→DEF／DEF→ABC、单组选中／ALL、持续按住、部分松开和稳定全松。测试从 Sony 原生 `0x8116` 按键接口进入，执行真实字符格式化、最终 LCD 图标接口和原生 `0x9E80` LCD 序列化流程；每次输出的 194 位与当前显示缓冲一致。物理 GPIO 在测试中只是观察边界，没有读取硬件。

在独立源码包根目录执行（在原工作区则先进入 `analysis/air_remote_ttl_multi_air2`）：

```powershell
python -X utf8 -B S/display/test_page_hint_integration.py --out page_hint_tests.json
python -X utf8 -B S/test_idle_retry_m2.py --out idle_retry_tests.json
```

运行后生成的 JSON 包含结果及实际镜像 SHA-256。原有完整渲染器的 8,192 个图标组合、1,024 个数字类型组合、2 个字母提示用例，以及最终 LCD 接口的 7 个门控用例均已通过。

同时修复 Sony AIR1 超时清除在待发送事务忙碌时丢失期限的问题：原生 `0x7316` 已将到期期限 `RAM54:55` 标为 `0xFFFF`，核心拒绝本轮清除时，M2 保留这一标记并返回原主循环；事务空闲后下一次原生检查会重试，成功才沿原 `0x808A→0xAD3E` 清零。AIR2 不进入重试保护，TTL 的 ABC 页仍由原模式门控排除。新增测试从真实上游 `0x8062` 进入，覆盖 12 个重试用例、10 个 AIR2／TTL 负例、2 个模式切换，以及 18 个原生输入／相机／队列／IRQ 待处理状态恢复后的重试用例。核心使用新采样的输入和发送就绪状态，不消费任何 IRQ 标记；没有替换任何原生函数，也不引入忙等。

本修复不修改 Sony 原厂 HSS 或无线发送算法。以上属于有边界的离线验证，未证明实机开机、显示可读时间或射频时序；旧 M1 安装包与已发布 Canon 固件保持不变。
