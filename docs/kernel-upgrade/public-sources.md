# Y700 四代 Android 内核 6.12：公开输入与证据核对

查询日期：2026-10-16，Asia/Singapore。范围为公开源码、仓库元数据、构建规则及发布页的只读核对；未下载大仓库、发布压缩包，未编译、未刷机。本文使用 docs-generator 的通用技术文档结构，flavor = null。

结论：找到针对 **TB322FC / elden / SM8750 sun 的社区 6.12 移植三仓**，并找到能提供 common 6.12、Kleaf、工具链和依赖清单的公开 LineageOS manifest。可以据此组装研究构建基线，但尚未证明已获得作者实际使用的完整冻结构建输入、设备打包配置或可直接刷入该 ColorOS 移植包的成套产物。**不能仅凭 SoC 仓库顶层 Makefile 的 6.11.0 否定此 6.12 移植：其 Kleaf 路径明确使用另一个 common 仓库的 Makefile。**

## 1. 官方规则：为何需要移植模块

### E-001：AOSP KMI 的稳定范围

来源类别：Google / AOSP 官方文档。

来源：<https://source.android.com/docs/core/architecture/kernel/stable-kmi>

原文：

> The KMI is only stable within the same LTS and Android version of a kernel, such as android14-6.1, android15-6.6 or android16-6.12.

另见 <https://source.android.com/docs/core/architecture/kernel/android-common>：

> KMI compatibility isn't maintained between different GKI kernels. So, for example, an android14-6.1 kernel cannot be replaced with an android15-6.6 kernel without rebuilding all modules.

复核方法：读取上述网页的正文；不需要登录。

事实：从 android15-6.6 到 android16-6.12 不在 Google 的同 KMI 兼容保证内。迁移必须核对并重编译厂商模块，不能把原 6.6 的 vendor_dlkm 与通用 6.12 Image 直接搭配视为可行方案。

### E-002：system_dlkm 必须与 GKI 一起构建

来源类别：Google / AOSP 官方文档。

来源：<https://source.android.com/docs/core/architecture/partitions/gki-partitions>

原文：

> GKI modules are signed by Google using the kernel build-time key pair and are compatible only with the GKI they're built with. There's no ABI stability between GKI and GKI modules; for modules to load correctly during runtime, GKI and GKI modules must be built and updated together.

厂商模块位置补充：<https://source.android.com/docs/core/architecture/partitions/vendor-odm-dlkm-partition>

> Note: These modules can have load-time dependencies on modules stored in (and loaded from) the vendor boot image.

事实：至少要检查 boot、vendor_boot ramdisk 内模块、vendor_dlkm、system_dlkm、DTB/DTBO，以及 modules.load / modules.dep。具体分区位置以本地包解析结果为准。

## 2. elden-6.12 社区三仓

### E-003：公开分支与固定提交

来源类别：社区，GitHub 用户 turbo-boo；不是 Lenovo 官方，也不是 Google 发布的设备适配。

2026-10-16 的 git ls-remote 结果：

- SoC / DDK 定义仓库：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750/tree/elden-6.12>，HEAD `587fb3b9e6a7fea873241b8c41b911bb8af495fb`。
- 外部模块仓库：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules/tree/elden-6.12>，HEAD `2f72151adab1ed228b9c6557ae64fbabc4388d2d`。
- 设备树仓库：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees/tree/elden-6.12>，HEAD `dd911f5c0b6c52417b44a8f7679785b0c284b412`。

复核命令，均只读取远端引用：

```bash
git ls-remote --heads --tags https://github.com/turbo-boo/android_kernel_lenovo_sm8750.git
git ls-remote --heads --tags https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules.git
git ls-remote --heads --tags https://github.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees.git
```

三仓均有 elden-6.12 与 lineage-23.2 分支；未返回 tag 引用。SoC 仓库的发布页显示 **“There aren’t any releases here”**：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750/releases>。其 Actions 页在匿名访问下显示启用 Actions 的引导页，未提供可核验的公开构建运行；Issues 页显示 Open 0。本次未找到下载地址、产物哈希、成功启动日志或完整硬件验收列表。

这只说明本次所查公开入口没有这些证据，不证明作者没有私有构建或测试。

### E-004：6.11 Makefile 的真实含义

SoC 仓库顶层 Makefile 确实写：

```make
VERSION = 6
PATCHLEVEL = 11
SUBLEVEL = 0
```

来源：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/Makefile>

但实际 Kleaf 规则没有使用它作为最终 kernel Makefile：

- [kleaf-scripts/dtbs.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/dtbs.bzl#L85) 明确 `makefile = "//common:Makefile"`。
- 同文件第 10 行为 `"KERNEL_DIR=common"`；第 29 行读取 `"//common:build.config.common"`，第 78 行使用 `"//common:kernel_aarch64_sources"`。
- [kleaf-scripts/android_build.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/android_build.bzl#L34) 同样生成 `KERNEL_DIR=common`，并加载 `//common:build.config.gki.aarch64`；perf 的基线是 `:msm_kernel_build`，代码注释和产物引用对应 `//common:kernel_aarch64`。
- [kleaf-scripts/consolidate.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/consolidate.bzl) 中 `kernel_build` 的源为 `srcs = ["//common:kernel_aarch64_sources"]`。
- [device.bazelrc](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/device.bazelrc) 启用 `--//build/kernel/kleaf:socrepo=true`。

复核命令：

```bash
curl -fsSL https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/dtbs.bzl
curl -fsSL https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/android_build.bzl
curl -fsSL https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/consolidate.bzl
```

结论：此仓库是新式 Qualcomm SoC / DDK 差异树，common 才提供内核核心。**不是已查到 Makefile 后部把 PATCHLEVEL 覆盖为 12，而是 Kleaf 指定了另一仓库的 Makefile。** 同理，SoC 树遗留 `build.config.common` 中 `BRANCH=android-mainline` 不足以代表最终 common 内核分支。实际 kernel release 必须从所配 common 固定提交及构建出的 include/config/kernel.release / Image 验证。

### E-005：移植来源与设备树配套

SoC 基线导入提交：<https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commit/45d961080a89e304e512fbe44c9eabc573451b52>

原文：

> Snapshot of https://github.com/LineageOS/android_kernel_qcom_sm8850 branch lineage-24.0 at 557159b6a0d06f1c6f07ec4c1f22bc9309a113e4, squashed to keep this repository small. The elden 6.12 changes follow as individual commits.

模块基线导入提交 `127a1f3572bdceb808ab25f931a935a195bc639e`，原文注明来自 LineageOS/android_kernel_qcom_sm8850-modules 的 `f2ecb6a09ea56bd8ec9a0bfd2e97f45e200ab322`。

设备树基线导入提交 `1c6b4f74d9b5caed903d2a653d7775b4f89140d0`，原文注明来自 LineageOS/android_kernel_qcom_sm8850-devicetrees 的 `297ae988607cbecb27d263f3c51c1ae7ea652a7b`。

已见明确三仓路径配套：

- [soc_repo_path.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/soc_repo_path.bzl)：`SOC_MODULES_REPO_PATH="vendor/lenovo/sm8750-modules"`。
- [msm_kernel_extensions.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/kleaf-scripts/msm_kernel_extensions.bzl)：加载 `//vendor/lenovo/sm8750-devicetrees:qcom/platform_map.bzl`，`get_dtstree()` 返回 `//vendor/lenovo/sm8750-devicetrees:msm_dt`。
- [platform_map.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees/blob/dd911f5c0b6c52417b44a8f7679785b0c284b412/qcom/platform_map.bzl#L851)：sun 目标列出 8 个 sun/sunp 基础 DTB、`sun-elden-overlay.dtbo`，以及 audio/camera/dsp/eva/gpu/hw-fence/mmrm/nfc/synx/vidc 等 SoC techpack overlays。
- [sun_perf.bzl](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/blob/587fb3b9e6a7fea873241b8c41b911bb8af495fb/configs/sun_perf.bzl) 包含 `CONFIG_ARCH_SUN=y`、`CONFIG_TOUCHSCREEN_NVT_SPI=m`、`CONFIG_LENOVO_HYPERSCHED=m`、`CONFIG_LENOVO_SYS_TEMP=m`、`CONFIG_AWINIC_HAPTIC_HV=m` 等设备选项。

事实：SM8850 名称的上游 SoC 仓库仍可包含 sun 平台支持，不能单凭上游仓库名断言它只支持 SM8850；这里的 sun 目标、elden DTBO 和 Lenovo 模块选项是具体配套证据。

社区维护者在设备树提交 `57e02aa875ffbc3a9383b8bd6c3c31e3701bee97` 说明：

> Board overlay for the elden (TB322FC) ... It reproduces the merged board overlay shipped in dtbo.img of the stock firmware ZUXOS 1.5.10.259 ... Lenovo has not published source for this overlay.

这是维护者对来源和还原匹配的声明，本文没有用官方原包独立重算 DTB 等价性，也不将“Lenovo has not published”扩展为对所有官方发布渠道的穷尽结论。

### E-006：已有调试细节，但没有成功启动的独立证据

以下都是可公开读取的维护者提交说明，足以证明适配涉及实际驱动和 ABI 问题；**不能单独证明当前 HEAD 已完成启动与硬件测试**：

- [调度死锁修复 25004b34](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commit/25004b346d498d6ca9f5e2cd52fa547b3ecf286d)：`The 6.12 port moved set_cgroup_hyper_prio() ... Every CPU locks up ... the boot hangs on the Lenovo logo`，随后描述把优先级工作独立并跳过 workqueue workers。
- [面板时钟修复 abbaaef8](https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commit/abbaaef85fa2155bf2b3a0c4dda7b3f1fd74a5ac)：NT36523 3-lane CPHY / DSC 需要 16/35 MND，缺少该比率会导致内核面板启动 PLL 错误。
- [设备树 CESTA 修复 dd911f5c](https://github.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees/commit/dd911f5c0b6c52417b44a8f7679785b0c284b412)：`probe failed with -ENODEV, mdss_mdp stayed deferred, /dev/dri was never created and the composer crashed on every start`，修复补入 disp_cc 区域。
- [硬件 fence 默认关闭 2f72151a](https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules/commit/2f72151adab1ed228b9c6557ae64fbabc4388d2d)：称原厂固件不回复新硬件 fence 控制消息，改为匹配原厂软件 fence 回退。
- [显示 UAPI 兼容 e9ceb41b](https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules/commit/e9ceb41b3d78293160d93dc5d59b170008fef6d9)：`Stock userspace ... was built against the 6.6 UAPI and never sends the appended fields`，实现旧 SPR / Demura / MDNIE / scaler 布局兼容。
- [EVA ABI de40102d](https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules/commit/de40102d2f8b57b8b5ef5f4b40851506627743e6)：保留 sun 的 490-word packet / 2264-byte eva_kmd_arg，避免新版 600-word 布局破坏未版本化 ioctl。

这些提交以 ZUXOS 1.5.10.259 为参照。用户的 ColorOS 移植包所含 vendor blob 是否相同，仍须与本地包比对；不能把原厂 ZUXOS 的 ABI 兼容说明自动转用为该 ColorOS 包的验证结果。

## 3. 可补齐的 common、Kleaf 和工具链

### E-007：LineageOS 公开 kernel-6.12 manifest

来源类别：LineageOS 社区项目；它引用的 android.googlesource.com/kernel/common 与 kernel/build 为 AOSP 官方仓库。

Manifest：<https://github.com/LineageOS/android/blob/d4c6331bc603e5038a9e48f5e526e7f10c8b96d9/snippets/kernel-6.12.xml>

当日 LineageOS/android 的 lineage-24.0 HEAD：`d4c6331bc603e5038a9e48f5e526e7f10c8b96d9`。

关键原文：

```xml
<project path="kernel/platform/kernel-6.12/build/kernel" name="kernel/build" revision="main-kernel-2025" remote="aosp" groups="kernel-platform,kernel-platform-612">
  <linkfile src="kleaf/bazel.sh" dest="kernel/platform/kernel-6.12/tools/bazel" />
  <linkfile src="kleaf/bzlmod/bazel.MODULE.bazel" dest="kernel/platform/kernel-6.12/MODULE.bazel" />
  <linkfile src="kleaf/bzlmod/bazel.WORKSPACE.bzlmod" dest="kernel/platform/kernel-6.12/WORKSPACE.bzlmod" />
</project>
<project path="kernel/platform/kernel-6.12/common" name="kernel/common" revision="android16-6.12-2026-06" upstream="android16-6.12-2026-06" dest-branch="android16-6.12-2026-06" remote="aosp" groups="kernel-platform,kernel-platform-612" />
```

同文件还列有 Clang、Rust、build-tools、kernel-build-tools、mkbootimg、Bazel rules、external/dtc 等依赖。它提供可解析的依赖基线，但多个依赖仍使用分支而非固定 SHA；若用于复现，应在同步时解析并保存全部 revision。

官方 common 的实读结果：

- 分支：`android16-6.12-2026-06`。
- `git ls-remote` HEAD：`f47396dab9818a8cf679ac4a711a30eb5cbc68ff`。
- [该提交 Makefile](https://android.googlesource.com/kernel/common/+/f47396dab9818a8cf679ac4a711a30eb5cbc68ff/Makefile)：`VERSION=6`、`PATCHLEVEL=12`、`SUBLEVEL=81`。
- 官方 build/kernel 的 `main-kernel-2025` HEAD：`08bb5611333aa1731ad7400e3f6e8af6500a1151`。

复核命令：

```bash
git ls-remote --heads https://github.com/LineageOS/android.git refs/heads/lineage-24.0
git ls-remote https://android.googlesource.com/kernel/common refs/heads/android16-6.12-2026-06
git ls-remote https://android.googlesource.com/kernel/build refs/heads/main-kernel-2025
curl -fsSL 'https://android.googlesource.com/kernel/common/+/f47396dab9818a8cf679ac4a711a30eb5cbc68ff/Makefile?format=TEXT' | base64 --decode
```

补充参照：<https://github.com/LineageOS/android_device_oneplus_sm8850-common/blob/lineage-24.0/lineage.dependencies> 的 `type=kernel, version=6.12` 会引入此类平台依赖；其 BoardConfigCommon.mk 明确 `TARGET_KERNEL_VERSION := 6.12`。它说明上游布局用途，不能把 OnePlus SM8850 设备配置直接用作 Y700 配置。

判断：这足够为“三仓 + common 6.12 + Kleaf”拟定一个**候选**构建输入集合；尚无证据说明此 common 版本就是 turbo-boo 测试使用的版本，所需 vendor hooks/符号/unsafe DDK 配置必须在真正的 Bazel analysis 和编译中核实。

## 4. 名称容易误读的 6.12 发布

### E-008：qdykernel 的 common-6.12 release

来源类别：社区，qdykernel / showdo 维护项目；不是 Lenovo 官方。

仓库：<https://github.com/qdykernel/Build_Lenovo_sm8750>

发布：<https://github.com/qdykernel/Build_Lenovo_sm8750/releases/tag/common-6.12>，页面显示标题 `common-refs_heads_android16-6.12`，标为 Pre-release。

读取资产列表：

```bash
curl -fsSL https://github.com/qdykernel/Build_Lenovo_sm8750/releases/expanded_assets/common-6.12
```

当日唯一非 GitHub 自动生成源码资产：

- `2025-06.tar.gz`，页面显示 242 MB。
- 页面显示 SHA-256 `a334a13df13beb6e354c54c31f271545aa3972f5b76d739d763855e8aec9c257`。
- 地址：<https://github.com/qdykernel/Build_Lenovo_sm8750/releases/download/common-6.12/2025-06.tar.gz>。
- 未下载，因此没有验证压缩包内容、内核版本或任何设备模块；页面摘要是构建缓存回退机制修改说明。

固定 tag `common-6.12` 对应提交 `fc866f09ce4d9cdc318e34fd07aa4e791f1d95af`。但 [该 tag 的工作流](https://github.com/qdykernel/Build_Lenovo_sm8750/blob/fc866f09ce4d9cdc318e34fd07aa4e791f1d95af/.github/workflows/Build_Lenovo_sm8750.yml) 实读仍为：

```yaml
options:
  - '6.6.56'
  - '6.6.89'
  - '6.6.102'
default: '6.6.89'
```

同工作流继续使用 `oki-android15-6.6` / `50_add_susfs_in_gki-android15-6.6.patch`，并从另一 `common` tag 下载 `${os_patch_level}.tar.gz`；没有出现构建 Y700 6.12 vendor_dlkm、DTB/DTBO 的成套路径。

判断：发布标题是线索，尚不能将此 release 认定为本任务需要的 Y700 6.12 成套内核产物；也不能在未查看压缩包内容时断言其中必然不是 6.12 源码。

## 5. 官方 Lenovo 来源的边界

本次核对未定位到明确标注 TB322FC / elden 的 Lenovo 官方 6.12 开源包或源码分支。`lenovo-basements` 和 `turbo-boo` 都属于社区来源。`lenovo-basements/android_kernel_lenovo_sm8750` 的 main 顶层 Makefile 实读为 6.6.104，turbo-boo 的 lineage-23.2 为 6.6.139，这两项不能充作 Lenovo 官方 6.12 依据。

这是一条有限检索结果，而非“Lenovo 全球所有渠道都不存在 6.12”的事实声明。社区的“Lenovo has not published source”说明也只作为其来源描述引用。

## 6. Findings 与下一条可实施路径

### F-001：存在真正针对 elden 的 6.12 移植候选

状态：validated（源码结构与三仓配套关系已观察）；置信度：high；证据：E-003、E-004、E-005。适用范围是公开源的存在与构建规则，不包含“已可用”的结论。

### F-002：顶层 Makefile 6.11 不代表最终目标 Image 版本

状态：validated；置信度：high；证据：E-004、E-007。原先只读顶层 Makefile 而推断“分支不是真正 6.12”的判断应撤销。最终实际版本依 common 输入和构建产物确认。

### F-003：当前没有已证明可直接刷入该包的 6.12 成套产物

状态：candidate / 未完成验证；置信度：high（对本次检索范围）；证据：E-003、E-006、E-008。公开仓库有大量具体移植修复，但未得到可核验的完整发布、构建日志、Image+模块+DTB/DTBO 哈希与设备测试结果。

### F-004：可组装候选构建，尚不能声称已获得验证齐全的完整复现输入

状态：candidate；置信度：medium；证据：E-003、E-004、E-005、E-007。主要缺口：作者实际使用的 common/build/toolchain 冻结 revision、所有平台构建 glue/linkfile、Y700/该 ROM 的镜像打包配置、模块加载清单，以及对该 ColorOS vendor UAPI 的兼容性确认。

### P-001：先构建验证，再形成适配产物

1. 固定 E-003 三仓 SHA 与 E-007 的 manifest 提交，逐项解析 manifest 分支并保存 revision lock。关联 F-001、F-004。
2. 使用三仓要求的 `vendor/lenovo/sm8750[-modules|-devicetrees]` 路径与 common 平台布局，补全 kernel/build / tools/bazel 等链接；先执行 Bazel query/analysis 核对 `sun_perf` 目标，确认 `//common:Makefile` 与 GKI 6.12.81 被选择。关联 E-004、E-005、E-007、F-002。
3. 编译 Image、配套 GKI 模块、全部 elden 厂商模块和 DTB/DTBO；核对 Module.symvers、vermagic、模块符号依赖、签名与实际模块全集。关联 E-001、E-002、F-004。
4. 与用户本地包逐项比较 vendor_boot 加载清单、vendor_dlkm、system_dlkm、ramdisk、镜像头和 DTBO；核对显示/摄像头/EVA 等厂商 ioctl 与 sysfs 行为，不能仅按 ZUXOS 参照做结论。关联 E-006、F-003。
5. 形成可审阅的完整镜像及回退材料后，在设备上验证启动、存储解密、显示刷新/亮度、触控/笔、Wi-Fi/蓝牙、音频、摄像头、双口 USB/充电、休眠唤醒、热控与稳定性。本文未执行此步骤，未授权任何自动刷写。

最终回答：**公开源码已足够推进到“补齐输入并尝试研究构建”；尚不具备可以声称“完整可复现且可用于该 ColorOS 包”的已验证构建输入。** 应优先沿 elden-6.12 三仓继续，不能把任意通用 GKI 6.12 镜像视为替代方案。
