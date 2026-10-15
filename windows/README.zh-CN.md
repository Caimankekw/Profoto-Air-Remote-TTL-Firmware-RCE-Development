# Windows 封装源码

[English](README.md) · 开发者：**Caimankekw** · 原创代码：**AGPL-3.0-only**

本目录将当前分支冻结的 **AIR2-P8-M2** 更新器封装为中英文 NSIS 解压向导和便携 ZIP。`../release_profile.json` 与 `../model.json` 锁定型号、固件和更新器指纹，以及原厂恢复输入。封装不改变运行固件、不访问 USB。各非 Canon 型号保留自身原厂 HSS，尚未通过实机验证。

## 构建

使用 Python 3.9+ 标准库。准备原厂更新器及同目录 `license_3rd_party.txt`，用根目录 `build.py` 重建 M2 更新器，再通过 `tools/package_source.py` 生成精确对应源码 ZIP。生成源码 ZIP 前应完成所有源码修改。

工具需要完整、未修改的 NSIS 3.13 目录，以及 7-Zip 26.04 x64 的 `7z.exe` 和同目录 `7z.dll`。`input_manifest.json` 固定整个 NSIS 目录、7-Zip 和原厂第三方许可的指纹，根配置固定各型号输入。工具路径显式传入，不自动下载。

```powershell
python -B windows/test_build_package.py
python -B windows/build_package.py `
  --updater "C:\inputs\Air-Remote-TTL-N-AIR2-P8-M2.exe" `
  --original "C:\inputs\Air-Remote-TTL-N-Firmware-C5.exe" `
  --vendor-notice "C:\inputs\license_3rd_party.txt" `
  --source-archive "C:\inputs\model-source.zip" `
  --source-sha256 "REPLACE_WITH_SOURCE_ARCHIVE_SHA256" `
  --nsis-dir "C:\tools\nsis-3.13" `
  --seven-zip "C:\tools\7zip\7z.exe" `
  --output "C:\output\new-model-package"
```

示例文件名属于 Nikon，实际使用当前分支锁定的 N/C5、S/A6、F/A5 或 O/A4。CLI 不能改选型号。输出目录必须尚不存在；不覆盖或删除输入及旧包。

源码 ZIP 使用唯一 `<name_slug>_Source/` 根目录及 `airremote-air2-branch-source-v1` 清单。共用源码解析器检查完整文件清单和冻结固件文件；封装器额外比较归档中全部 `windows/` 文件、根许可文档及型号配置与当前目录是否完全一致。

## 产物与验证

输出包括带型号的 `Custom-Updater.exe`、`Windows-portable.zip`、解压内容、`package_verification.json`、校验和以及编译/解包日志。包内包含冻结 M2 GUI、匹配的原厂恢复 GUI、精确对应 `source.zip`、中英文说明/法律文档/变更记录、原厂第三方许可、NSIS 许可和文件清单。

向导以当前用户身份运行，拒绝使用已占用目录，默认不勾选打开更新器；提供中英文免责声明和 AGPL 页面。不安装驱动、不静默更新、不删除文件，也不增加卸载流程。原厂更新器仍有自身的运行要求。

封装过程只执行指定编译器和归档解包工具。检查逐字节比对便携包和静态解包的每个 NSIS 文件，包括预期 NSIS 组件；检查 PE 产品/开发者信息和 `asInvoker`。不运行安装包或更新器。完整 GUI 的哈希固定；固件镜像哈希标识此前构建预期，不代表额外的设备实测。不承诺外层 EXE 字节级复现，静态检查也不代替 Windows 界面或真机测试。

原 NSIS 许可保留在 `vendor/NSIS-COPYING.txt`。原创封装代码遵循根 LICENSE，厂商材料保留原有权利，范围详见中英文 NOTICE 和免责声明。
