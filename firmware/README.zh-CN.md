# Air Remote TTL N/S/F/O · AIR2-P8-M2

[English](README.md) | 简体中文

开发者：**Caimankekw** · 原创代码：**AGPL-3.0-only**

**M2 为 Canon P8 对照后的修复版，四款最终镜像已通过有边界的离线回归和 HSS 保留检查。** 尚未验证四个型号的实机启动及操作。每次发布均须通过独立源码重建和便携包校验，结果记录在对应发布目录中。四个型号独立处理：

| 型号标记 | 设备 | 原厂输入版本 |
|---|---|---|
| N | Air Remote TTL-N，Nikon | C5 |
| S | Air Remote TTL-S，Sony | A6 |
| F | Air Remote TTL-F，Fujifilm | A5 |
| O | Air Remote TTL-O，Olympus | A4 |

每个型号须有自己的已审阅镜像和便携 ZIP，不能混用其他卡口的更新器。本项目为非官方实验修改，不表示与厂商合作或获得认证。使用前请阅读[免责声明](DISCLAIMER.zh-CN.md)、[LICENSE](LICENSE) 和[许可范围](NOTICE.zh-CN.md)。

## 已实现行为

AIR2 控制策略参考 Canon AIR2-P8：MAN AIR1 相对调节、MAN AIR2 绝对目标、ABC/DEF 六组分页、C＋HEAD 翻页、MAN 中 C＋MODEL 切换 AIR1/AIR2。TTL 吞掉 C＋MODEL 且不改上次手动类型；A/B/加/减不进入辅助键组合等待。AIR1 成功编辑后临时显示，已开启 AIR2 目标持续显示。离线回放覆盖这些路径，实际按键和灯端表现仍须实机验收。

TTL 的 ABC 为曝光补偿，DEF 按记住的 AIR1/AIR2 类型进行手动控制，**不是六组自动 TTL**。mixed ALL 同时调节 ABC FEC 与 DEF 手动值；DEF 的绝对更新发送完整六槽命令，也可能刷新 ABC 手动目标缓存。相机曝光及调整后的第一张 TTL 照片需另行验证。

**保留每个型号自己的原厂 HSS、相机协议和射频调度实现，不移植 Canon HSS-P3 修改。** 扩展通过原生队列提交 16 字节命令体，由原调度器处理，不替换 UART 发射器，也不强制改变发射速率。进入队列不等于灯具收到或执行；队列满时当前帧继续等待，事务进行期间的新编辑可能被拒绝。不承诺任意速度下零丢键或与 Connect Pro 性能相同。

**四个版本均已启用参数持久化。** 带型号标记的 V5 记录保存当前 TTL/MAN-AIR1/MAN-AIR2、上次手动类型、页面、六组 AIR2 目标和 Head/Model 状态，使用 `0xF800`/`0xFC00` 两个独立页并保留原厂日志区；不导入 Canon V1–V4 或其他卡口记录。保存/重新读取路径已通过有限离线回放，实际掉电行为尚未实测。读取设置本身不会让灯端自动同步。存储范围、RAM、钩子、调用约定、显示和计时单位均按型号处理，不默认沿用 Canon 地址。

四卡口仍保留独立的存储失败策略：一次擦写或读回失败后，本次上电停止继续保存，重启后重新尝试；Canon P8 保留待保存状态并稍后重试。此差异不是启动掩码修复的一部分，也不表示之前修改一定已落盘。原生异步队列与 Canon 同步发送的时序同样不同；快速按键响应仍需实机验证。

## M2 修复范围

- 四型号：启动恢复遇到原生模式变化时，保留已保存的 ABC Head/Model 状态，避免默认值覆盖后再次落盘。
- 四型号：AIR1 临时数值到期时若原生处理忙，保留到期条件，在空闲后重试清屏，避免一次拒绝后永久残留。
- Fujifilm：从真实原生 idle 入口覆盖 TTL/DEF/AIR1 的到期清屏；ALL 选中时同时显示三行选框。
- Sony：在 C＋HEAD 翻页路径调用实际页面字母提示，稳定全松后恢复当前页功率显示。

若旧 M1 已把错误开关状态保存进记录，M2 无法推断覆盖前的值；升级后请手动核对并重新设置六组 Head/Model。同型号有效 V5 记录继续按原字段加载。

Canon 对照以用户已实机通过的冻结 AIR2-P8 镜像为基准，原发布包保持不变。对照也发现 Canon 同类 AIR1 忙时到期问题，由独立 AIR2-P8-FIX1 修复分支处理；FIX1 仍需实机验收，不能继承原 P8 的实机结果。正常无线帧匹配不能代替启动、UI 或全部忙态行为验证。

## 开发证据

`shared/NATIVE_BACKEND_ABI.md` 定义公共核心与原生适配接口。`shared/stock_inventory.json` 记录原厂 EXE 指纹和原厂镜像解码检查，不证明 AIR2 移植完成。各型号目录保存对应分析与测试；封包前必须通过公共核心、原生适配、整合、原 HSS 保留和持久化后端的最终镜像检查。离线检查不代替启动、射频、曝光、长期运行或掉电实测。

普通 Python 和 `python -O` 各通过 312 项整合、96 项启动恢复和 226 项型号专项回归；优化模式检查关键验证不会随断言关闭而消失。正常无线帧 1,024 项匹配，每型号 26 条正常操作轨迹（178 步）匹配。另有 12 条调度边界轨迹记录与 Canon 的既有准入差异，不能称为全忙态等价。精确计数与镜像哈希见[验证摘要](shared/final_validation_m2.json)。

每次发布还须从实际源码 ZIP 解压到独立目录，使用单独提供且固定哈希的原厂 EXE 重建，比较自定义 EXE、HEX 与局部明文；最终结果以发布目录的 `source_rebuild_verification.json` 为准。本源码包不依赖旧 Canon 工作区。以上检查不等于无线已实际送达、硬件 HSS 时序已验证或所有相机均兼容。

便携打包器仅处理已有且通过审阅的产物，不运行固件、更新器、USB 命令或 GitHub 发布动作；本目录不创建远程仓库、不上传 Release。

## 从对应源码包独立重建

使用 Python 3.9 或更高版本及其标准库。解压 `source.zip` 后，在其顶层目录执行命令；不需要旧 Canon 工程、Canon 固件、APK、账号会话或开发者原工作目录。包内 `shared/reference/c11_offset_transform.bin` 为 73,725 字节、固定哈希的派生字节变换参数表，**不是厂商固件镜像**。

请自行提供未修改的原厂 EXE，按以下路径放置；源码包有意不携带这些原厂二进制。准备便携包时，将原厂 `license_3rd_party.txt` 一并保留在对应 EXE 旁。

```text
inputs/air_remote_ttl/
  air-remote-ttl-n-firmware-c5-win/Air-Remote-TTL-N-Firmware-C5.exe
  air-remote-ttl-s-firmware-a6-win/Air-Remote-TTL-S-Firmware-A6.exe
  air-remote-ttl-f-firmware-a5-win/Air-Remote-TTL-F-Firmware-A5.exe
  air-remote-ttl-o-firmware-a4-win/Air-Remote-TTL-O-Firmware-A4.exe
```

原厂 EXE 指纹固定于 `shared/stock_inventory.json`，代码会再次检查。先通过 `inspect_variants.py` 在本地重新生成原厂 HEX、局部明文与已知字节掩码；这些是构建输入，不是源码归档内容。随后**每个型号用独立 Python 进程**构建：

```powershell
$firmwareRoot = (Resolve-Path '.\inputs\air_remote_ttl').Path
python -B shared\inspect_variants.py --firmware-root $firmwareRoot
if ($LASTEXITCODE -ne 0) { throw 'Stock inspection failed' }
$variants = @{ N='C5'; S='A6'; F='A5'; O='A4' }
foreach ($tag in 'N','S','F','O') {
  $revision = $variants[$tag]
  $folder = 'air-remote-ttl-' + $tag.ToLower() + '-firmware-' + $revision.ToLower() + '-win'
  $original = Join-Path (Join-Path $firmwareRoot $folder) ('Air-Remote-TTL-' + $tag + '-Firmware-' + $revision + '.exe')
  python -B shared\build_variants.py --model $tag --profile "$tag\port_profile.json" --source $original --output "build\$tag"
  if ($LASTEXITCODE -ne 0) { throw ('Build or replay failed: ' + $tag) }
}
```

只处理单一型号时，可在原厂解析命令加 `--model N`，随后仅执行该型号构建。请显式传入 `--firmware-root` 与 `--source`；默认路径同时兼容原开发工作区，不应依赖其推断。构建器要求 profile 已经审阅并标记 `offline_qualification_complete`、全部必要验证通过，且最终链接机器码回放无待补覆盖；资格尚未完成的候选 profile 会被拒绝，不应绕过关卡封包。

相同源码快照、profile 与固定原厂 EXE 应逐字节重现自定义 EXE。重新生成的验证 JSON 可能带有不同本地路径和源码清单哈希，不要求报告文件本身逐字节一致。生成的 `.hex` 与 `.partial.bin` 保留为开发输出，不应单独刷写。`tools/package_source.py --check` 仅在内存验证明确的源码清单与 ZIP 结构；源码冻结后显式传入 `--output NEW.zip` 才写出源码归档。

源码包包含实际共享/嵌套型号依赖、有限范围的最终镜像测试与必要 ABI 证据；排除历史匹配脚本、完整 parity_review 采集、大型临时分析、候选镜像/反汇编清单及旧独立 PASS 报告，不承诺复跑全部探索分析。Sony/Fuji 使用包内汇编器支持，这不意味着引入 Canon HSS 策略。

新增回归脚本默认从源码根的 `inputs/air_remote_ttl/` 读取原厂 EXE；若本地存在错误文件，必须通过指纹检查并明确报错，不能退回其他输入。首次运行前先完成上面的原厂输入解析。`shared/test_boot_restore_m2.py`、各型号的 M2 idle/UI 回归都可在此独立目录执行。

## 便携封包合同

`tools/package_portable.py` 接收一个型号的自定义 EXE、固定哈希的原厂 EXE、补丁计划、重封装报告、最终 readiness 记录及对应源码 ZIP。拒绝仅原厂/候选材料、未完成检查、其他型号、文档或源码变化、未声明的传输字节修改，以及已存在的输出路径。`--check` 只在内存准备；显式 `--export` 才创建新目录和 ZIP。

每包包含所选型号的自定义 GUI、未修改的原厂恢复 GUI、中英说明/免责声明/许可、对应源码 ZIP、精简证据及 SHA256。包内不放裸 BIN/HEX、设备采集、其他型号固件或 NSIS 外壳。源码 ZIP 须包含所需公共依赖，不能仅因本开发目录存在就声称可以独立重建。

原厂 `license_3rd_party.txt` 为必需材料，按已知哈希检查后原样附入。默认从原厂 EXE 同目录读取，也可用 `--third-party-notices` 指定。源码 ZIP 采用单个顶层目录及 `source_manifest.json`，以 `size`、`sha256` 列出除清单自身以外的全部文件；必要二进制参考输入须逐项声明，排除可执行产物、私人采集和账户文件。

readiness 格式为 `multi-air2-portable-readiness-v1`，状态须为 `OFFLINE_VALIDATED_EXPERIMENTAL`。它固定型号/版本、EXE/原厂/计划/封装报告/源码哈希、打包脚本及七份根文档哈希，并绑定同一最终镜像的通过报告，覆盖 `core`、`native_adapter`、`integration`、`hss_preservation`、`persistence_backend`。`nv_enabled` 须与持久化报告一致；明确关闭的后端可以通过“关闭路径”检查，但不能称为保存功能通过。`export_authorized` 是构建审阅关卡，不是硬件测试。

```powershell
python tools/package_portable.py --model N `
  --updater "N\build\Air-Remote-TTL-N-AIR2-P8-M2.exe" `
  --original "inputs\Air-Remote-TTL-N-Firmware-C5.exe" `
  --plan "N\build\patch_plan.json" `
  --repack-report "N\build\verification.json" `
  --readiness "N\build\portable_readiness.json" `
  --source-archive "inputs\AIR2-P8-M2-source.zip" `
  --output "release\N-AIR2-P8-M2" --check
```

最终审阅后将 `--check` 替换为 `--export`。示例仅说明接口，不表示上述候选文件已经存在。精确 readiness 字段由脚本 `--schema` 输出。

## 已有通过校验的包之后如何实机验收

完整解压匹配型号的 ZIP，先读型号专属 `PACKAGE.md`，再通过自定义 EXE 的原图形界面连接、确认设备并手动更新。本包不会自动完整备份或刷写。保留对应原厂恢复 GUI，但其存在不保证恢复成功。

先检查电池开机、显示和按键，再检查分页/模式、未到边界时逐次五次 ±0.1、灯端实际功率、Head/Model、ABC FEC 与 DEF 手动、六组触发、原 HSS 和 TTL 曝光。仅在包声明持久化启用时验证保存/重启，并另测首次曝光。文件哈希或更新成功界面不能替代这些结果。
