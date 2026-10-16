# Y700 四代 elden：6.12 内核构建

为 `TB322FC_CN / SM8750 sun` 的 `c16-300-9008-V17.6` 一加系统移植包准备 Linux 6.12 内核组件。当前正在验证源码集成与 GitHub Actions 首次构建。

原包基线为 Android 16 系统层、Android 15 厂商层，以及 4 KiB 页的 `6.6.89-android15-8` 内核。原始镜像保留在本地并由 `.gitignore` 排除。

## GitHub Actions

工作流：[Build elden kernel 6.12](.github/workflows/build-kernel.yml)。使用普通 GitHub 托管的 Ubuntu 24.04 x86_64 runner，手动触发，单次只跑一个构建。

实际执行和排错记录见 [Actions 构建记录](docs/kernel-upgrade/actions-build.md)。

```sh
gh workflow run build-kernel.yml --repo NzflpKfnjos/y700-c16-kernel --ref main
gh run list --repo NzflpKfnjos/y700-c16-kernel --workflow build-kernel.yml
```

流程：清理 runner 的预装 SDK → 同步冻结的公开源码 → 配置 Qualcomm Kleaf 工作区 → 构建 sun/elden perf 目标 → 检查 ARM64/6.12/4 KiB 页/模块 → 保存产物。

- 每次运行均尝试保存 `elden-6.12-diagnostics-运行编号`，包含同步、构建日志以及实际解析的源码清单。
- 构建和组件检查通过后才上传 `elden-6.12-components-运行编号`，包含压缩后的 dist、SHA256 和检查说明。
- 产物保存 7 天，不自动发布 GitHub Release。

## 构建输入与边界

- [CI 源码版本锁](ci/source-lock.json)和[repo manifest](ci/manifests/elden-6.12.xml)记录实际使用的来源和提交。
- [源码调查](docs/kernel-upgrade/public-sources.md)和[构建输入核对](docs/kernel-upgrade/elden-build-inputs.md)保留前置调查及其限制。
- 这是一组正在集成、尚需通过编译验证的社区移植输入。固定提交用于复现，不能代替构建成功证据。

组件检查通过表示镜像版本、页大小和若干设备驱动结构符合检查条件。它不代表已完成 ABI/UAPI 全量核对、现有 ROM 的 ramdisk/HAL/AVB 集成或真机硬件测试。dist 中即使出现 `super.img`，也可能只是构建系统生成的 DLKM 组合镜像，不能替代原包完整的 22 GiB super 分区。

## 本地镜像检查

```sh
python3 tools/inspect_boot.py --images c16-300-9008-V17.6/images --out .work/preflight
python3 tools/inspect_super.py c16-300-9008-V17.6/images/super.img --collect
```

前者依赖 Python 3 和 lz4；后者的选中文件提取还依赖 `dump.erofs`，支持通过 `--erofs-tool` 指定路径。完整说明见[升级工程记录](docs/2026-10-16_内核升级-y700-c16-report.md)。
