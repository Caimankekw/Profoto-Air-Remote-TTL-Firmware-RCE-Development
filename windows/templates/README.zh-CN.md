# Air Remote TTL-@MODEL@ AIR2-P8-M2 Windows 更新包

[English](README.md) · 开发者：**Caimankekw** · **@RELEASE_DATE@** · `@TAG@`

此实验固件仅适用于 **Air Remote TTL-@MODEL@（@BRAND@）**，不是 Profoto 官方发布。请先阅读[免责声明](DISCLAIMER.zh-CN.md)、[LICENSE](LICENSE) 和 [NOTICE](NOTICE.zh-CN.md)。原创自定义代码采用 AGPL-3.0-only；厂商固件、更新器和第三方材料保留各自条款。原厂第三方许可保留在 `license_3rd_party.txt`。

**本型号 M2 镜像尚未进行实机开机或相机测试。**离线无线、显示、记忆及 HSS 保留检查不代表真机验证通过。Canon P8 的实测结果不能代替本型号验证。继续保留本型号原厂 **@STOCK_REVISION@ HSS**，没有移入 Canon HSS-P3。

源码：[发布快照](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/@TAG@) · [开发分支](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/@BRANCH@)。精确对应源码随包提供为 `source.zip`，其 SHA256 记录在 `package_manifest.json`，内部 `source_manifest.json` 列出全部源码文件。

## 使用方法

1. 运行安装包，选择中文或英文，阅读免责声明及许可，选择新的解压目录。默认目录是 `%LOCALAPPDATA%\Caimankekw\AirRemote-TTL-@MODEL@\AIR2-P8-M2`。外壳仅解压文件，不安装驱动、不访问 USB，也不刷写设备。
2. 完成页的“打开更新器”为可选项，**默认不勾选**。也可手动打开解压目录中的 `@UPDATER_NAME@`。使用便携 ZIP 时，先完整解压。
3. 仅连接目标 Air Remote TTL-@MODEL@，遵循原厂图形界面提示，核对识别型号后手动开始更新，保持连接直到完成。
4. 断开 USB，用电池正常开机，先检查显示、菜单和按键，再进行相机测试。若出现 `EC!` 且原厂更新器仍能通信，可用 `restore_original/Air-Remote-TTL-@MODEL@-Firmware-@STOCK_REVISION@.exe` 尝试恢复；不保证可恢复。

固件资源之外的厂商容器保持原字节。修改后的更新器不具备有效原厂签名，外层安装包未签名。不提供替代命令行刷写器。外层以普通用户权限运行，原更新器自身运行条件仍然适用。

## AIR2 操作与边界

- **C＋HEAD**：TTL 和 MAN 均可切换 ABC/DEF 页。
- **C＋MODEL**：MAN 切换 AIR1/AIR2；TTL 吞掉此组合且不改变记住的手动类型。组合键不会额外切换 Head/Model。
- AIR2 同时显示已启用各组绝对功率目标；AIR1 保留短暂显示相对值的行为。TTL 的 ABC 为曝光补偿，DEF 使用记住的 AIR1/AIR2 手动类型，**不是六组自动 TTL**。
- ALL 影响六组。AIR2 功率和 Head/Model 状态可保存，上次 MAN 子类型可恢复。需要同时核对引闪器显示和灯具实际表现。
- A、B、加、减不增加组合等待。原生扫描和无线事务忙仍会限制按键接收，忙时调节可能拒绝而不排队；不能据此宣称连按接收率及忙时序与 Canon 完全一致。

M2 修复延迟启动期间保存的 Head/Model 状态被覆盖，以及忙时 AIR1 到期数值未清除的问题；各型号显示修复见[变更记录](CHANGELOG.zh-CN.md)。M1 已经错误保存的开关状态无法反推，升级后应主动检查并设置 Head/Model。检测到 NVM 保存失败后，本次供电周期会保持失败锁存；断电记忆需要独立测试。

## 内容与验证

包内提供冻结的 M2 更新器、匹配的原厂恢复更新器、对应源码、中英文文档、许可和清单。封装不改变固件运行字节。

- M2 更新器 SHA256：`@UPDATER_SHA256@`
- 预期 partial 固件镜像 SHA256：`@IMAGE_SHA256@`

partial BIN 仅为研究和构建产物，**禁止直接刷写**。封装检查完整更新器指纹、源码清单、便携 ZIP、PE 元数据及静态解包后的全部 NSIS 文件，不运行交付的更新器或安装包。具体结果见 Release 的 `package_verification.json` 和 `SHA256SUMS.txt`。

使用交付 GUI 不需要 Python。重建外壳时解压 `source.zip` 并参照 `windows/README.zh-CN.md`。未修改的 NSIS 3.13 组件保留 `NSIS-COPYING.txt` 中的许可，[NSIS 源码](https://sourceforge.net/projects/nsis/files/NSIS%203/3.13/)另行提供。
