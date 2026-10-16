# GitHub Actions 6.12 构建记录

仓库：<https://github.com/NzflpKfnjos/y700-c16-kernel>（私有）。用户已明确授权使用 GitHub Actions 编译。

## 首次运行

- URL：<https://github.com/NzflpKfnjos/y700-c16-kernel/actions/runs/38928748770>
- 触发时间：2026-10-17 00:02:19（Asia/Singapore）。
- 提交：`1f4bb2f2b7bd2189c8eb56420e90f59bf91dd7e5`。
- 目标：`//vendor/lenovo/sm8750:sun_perf_dist`，4 KiB 页。
- Runner：标准 GitHub 托管 `ubuntu-24.04`，并行编译任务数 2。
- 结果：2 分 12 秒后在同步阶段失败。Google 源码站的 `kernel/common-modules/wonder` fetch 返回 HTTP 503；尚未进入工作区准备或内核编译。
- Runner 实测：清理预装 SDK 后可用空间 111.3 GiB。
- 诊断产物：`elden-6.12-diagnostics-1`，已下载到本地 `.work/actions/run-1-diagnostics/`。

修复：移除 repo sync 的 fail-fast，让独立项目完成下载；在同一工作区为未完成项目做最多三次整体同步尝试，间隔 15/30 秒。仍保留所有固定提交验证，未通过改变源码版本来掩盖下载错误。

## 本轮补齐的构建输入

42 个源码项目和 repo 工具均锁定提交；构建从公开源码同步，不上传本地原始固件镜像。源码清单省去与该内核独立的 GBL/Fuchsia/LTP 项目，以减少 runner 磁盘占用。

前期调查中的 AOSP Kleaf `08bb561…` 没有 Qualcomm `socrepo` 和 DDK `pkvm_el2` 规则。本次改用真实的 Qualcomm `kernel.lnx.6.12.r69-rel` 构建工具，固定为 `af73dd2482b6e6d4ea181f378a4b49fb7970655f`；具体来源见 [CI source lock](../../ci/source-lock.json)。ACK common 使用固定 6.12.81 输入。是否兼容由真实构建检验。

工作区准备脚本补齐 nested Lenovo 路径、Qualcomm build extension 链接、DTC BUILD 声明和由 DTC Makefile 生成的版本头；变动会以 patch 和 JSON 保存在诊断产物中。没有通过伪造模块符号或跳过编译错误来标记成功。

构建图依据和产物限制见 [构建图核对](actions-build-graph.md)。

## 已执行的本地验证

- `actionlint 1.7.12` 检查 workflow 通过；工具来自官方 GitHub release，下载包 SHA256 已核验。
- CI Python 脚本语法、shell 语法检查通过，固定 manifest 的 `--plan` 校验通过。
- 工作区准备脚本经过 fixture 检查：支持重复运行、保留 manifest 引用的源文件、拒绝非 6.12 输入和错误页配置。
- 使用原包真实的 6.6 Image 与模块归档运行产物校验器，正确返回失败；缺少设备树时同样失败。

## CI 产物校验和交付边界

通过条件包括 ARM64 Image 的 6.12.x banner、4 KiB Image 标记与内核配置、模块版本及其补丁号与 Image 一致、符号版本节、指定设备驱动和 DTB/DTBO 镜像存在。损坏归档或解压失败也会导致失败，并保存诊断。

该检查不代替完整 Module.symvers/KMI 检查、现有 vendor HAL 的 UAPI 验证、ramdisk 模块加载顺序和真机测试。当前构建系统生成的 DLKM-only `super.img` 与 ROM 完整 super 不同；默认测试签名和通用 boot 参数也需要进一步集成。只有构建与上述检查都通过，才上传组件压缩包；失败时保留诊断产物。
