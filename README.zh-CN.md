# Air Remote TTL-S · Sony A6 原厂固件逆向

[English](README.md) | 简体中文

开发者：**Caimankekw** · 原创分析及工具：[AGPL-3.0-only](LICENSE)

本分支整理**未修改的 Sony Air Remote TTL-S A6** 已恢复逻辑。[逆向说明](reverse/README.zh-CN.md)包含注释伪代码、原函数/RAM 契约及证据，未恢复的辅助函数明确保留边界。不是厂商完整源码或可重编译原厂固件工程，不含 AIR2 补丁。自定义固件见 [sony-air2-m2](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development/tree/sony-air2-m2)；其他品牌见 [main](https://github.com/Caimankekw/Profoto-Air-Remote-TTL-Firmware-RCE-Development)。

## 只读提取

使用 Python 3.9 或更新版本，自行提供未修改的 `Air-Remote-TTL-S-Firmware-A6.exe`：

```powershell
python -B tools/inspect_original.py --original "C:\firmware\Air-Remote-TTL-S-Firmware-A6.exe" --output "build\stock"
```

输出目录必须尚不存在。[model.json](model.json)固定输入身份，原厂 EXE SHA-256 为 `707b65d9cb6ea6c320976e5a6244de05b1f0856ab9c7ddc5008fe739337b9737`。详见[工具说明](tools/README.zh-CN.md)。工具不运行更新器、不写设备、不产生修改版 EXE。

通用字节变换仅恢复 `[0x4002,0x10000)`；开头两字节未知，文件中为占位。高地址 FF 尾部依赖已知 opaque suffix 指纹，不代表任意尾部都可解码。生成的局部 BIN 仅供分析，不能直接刷写。

HSS 证据覆盖已识别的原厂调用链与区间，不等于完整 HSS 算法或实测物理时序。请阅读[免责声明](DISCLAIMER.zh-CN.md)、[许可范围](NOTICE.zh-CN.md)及 [LICENSE](LICENSE)。厂商代码保留原有权利。
