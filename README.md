# Y700 四代 elden：6.12 内核构建

为 `TB322FC_CN / SM8750 sun` 的 `c16-300-9008-V17.6` 一加系统移植包，将 Linux 6.6 内核升级到 6.12。最终验收目标是：基于原包生成 9008 刷机包，设备能够正常开机，并验证锁定 BL 下 KSU 修补后的 `init_boot` 经项目签名工具签名后可以刷入并启动。

当前已完成 GitHub Actions 6.12 组件构建、ROM 镜像集成和 9008 静态候选组装；尚未完成真机 9008 刷写、6.12 启动和硬件功能验证。用户已有独立实测：锁定 BL 下，KSU 修补的原版 `init_boot` 签名后可以开机。

原包基线为 Android 16 系统层、Android 15 厂商层，以及 4 KiB 页的 `6.6.89-android15-8` 内核。原始镜像保留在本地并由 `.gitignore` 排除。

## GitHub Actions

工作流：[Build elden kernel 6.12](.github/workflows/build-kernel.yml)。使用普通 GitHub 托管的 Ubuntu 24.04 x86_64 runner，手动触发，单次只跑一个构建。

实际执行、产物下载和排错记录见 [Actions 构建记录](docs/kernel-upgrade/actions-build.md)。

```sh
gh workflow run build-kernel.yml --repo NzflpKfnjos/y700-c16-kernel --ref main
gh run list --repo NzflpKfnjos/y700-c16-kernel --workflow build-kernel.yml
```

流程：清理 runner 的预装 SDK → 同步冻结的公开源码 → 配置 Qualcomm Kleaf 工作区 → 构建 sun/elden perf 目标 → 检查 ARM64/6.12/4 KiB 页/模块/设备树 → 保存产物。

- 每次运行均尝试保存 `elden-6.12-diagnostics-运行编号`，包含同步、构建日志以及实际解析的源码清单。
- 构建和组件检查通过后才上传 `elden-6.12-components-运行编号`，包含压缩后的 dist、SHA256 和检查说明。
- 产物保存 7 天，不自动发布 GitHub Release。
- 成功运行：<https://github.com/NzflpKfnjos/y700-c16-kernel/actions/runs/38936781318>；产物中的 `boot.img` 使用与原 ROM 根密钥一致的 RSA4096 AVB 公钥，可用项目签名工具验证。

## 9008 候选包

基于本地 `c16-300-9008-V17.6` 组装的静态候选位于 `.work/9008-candidate-c16-6.12`。它保留原始 9008 XML 和未改动分区，只替换 6.12 的 `boot.img`、`vendor_boot.img`、`dtbo.img`、`super.img`、`vbmeta.img`，并附有 `SHA256SUMS.txt`。详细替换清单、验收结果和未验证项见 [9008 候选包说明](docs/kernel-upgrade/9008-candidate.md)。

候选包尚未经过真机 9008/Firehose 或启动验证，不能把静态验收当成可用性保证。测试前必须保留原始包，以便回刷。

## 构建输入与边界

- [CI 源码版本锁](ci/source-lock.json)和[repo manifest](ci/manifests/elden-6.12.xml)记录实际使用的来源和提交。
- [源码调查](docs/kernel-upgrade/public-sources.md)和[构建输入核对](docs/kernel-upgrade/elden-build-inputs.md)保留前置调查及其限制。
- [过程与经验总结](docs/kernel-upgrade/progress-and-lessons.md)记录从原包盘点到静态候选的步骤、关键决策和最终验收标准。
- 6.12 内核来自公开社区 elden 三仓和固定的 ACK/Kleaf 构建输入；Actions run `38936781318` 已完成真实编译和组件检查。固定提交用于复现，不能代替真机启动和硬件验证。

组件检查通过表示镜像版本、页大小和若干设备驱动结构符合检查条件。它不代表已完成 ABI/UAPI 全量核对、现有 ROM 的 ramdisk/HAL/AVB 集成或真机硬件测试。dist 中即使出现 `super.img`，也可能只是构建系统生成的 DLKM 组合镜像，不能替代原包完整的 22 GiB super 分区。

## 本地镜像检查

```sh
python3 tools/inspect_boot.py --images c16-300-9008-V17.6/images --out .work/preflight
python3 tools/inspect_super.py c16-300-9008-V17.6/images/super.img --collect
```

前者依赖 Python 3 和 lz4；后者的选中文件提取还依赖 `dump.erofs`，支持通过 `--erofs-tool` 指定路径。完整说明见[升级工程记录](docs/2026-10-16_内核升级-y700-c16-report.md)。
