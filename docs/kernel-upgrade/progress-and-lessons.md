# Y700 四代 6.6 → 6.12 过程与经验

本文记录以 `c16-300-9008-V17.6` 为唯一基线，将 Y700 四代一加系统移植包从 Linux 6.6 升级到 6.12 的过程。最终目标是生成可由 9008 刷入的包，设备正常开机，并验证锁定 BL 下 KSU 修补后的 `init_boot` 经项目 RSA4096 工具签名后可以刷入和启动。

## 当前状态

已经完成公开源码锁定、GitHub Actions 6.12 构建、原包静态集成和 9008 候选验收。候选目录为 `.work/9008-candidate-c16-6.12`，使用原版 `init_boot.img`，尚未集成实际 KSU patched `init_boot`，也没有进行真机 9008/Firehose 刷写或 6.12 启动验证。

用户已有一条独立设备证据：锁定 BL 下，KSU 修补原版 `init_boot`，再用项目签名工具处理后可以开机。这证明原 ROM 的信任根和该工具的 RSA4096 公钥关系具有实际参考价值，但不等于 6.12 候选已经启动。

## 过程

1. **固定原包基线**：只读取 `c16-300-9008-V17.6`，记录 boot/init_boot/vendor_boot/dtbo/vbmeta/super 结构、6.6.89 banner、4 KiB 页、vendor ramdisk 模块、DLKM 模块、VINTF 和 rawprogram XML。原包目录不直接修改。
2. **确认公开构建输入**：选择 elden/sun 6.12 三仓，补齐 ACK common、Qualcomm Kleaf、工具链和依赖，形成 42 项目冻结 manifest。macOS 不直接编译，使用 GitHub Actions Ubuntu 24.04 x86_64 runner。
3. **处理 Actions 失败与重试**：第一次失败是公开源 HTTP 503；第二次在持续编译阶段被过早取消；第三次按 query/build 分阶段运行并完成，得到 `6.12.81-android16-6-maybe-dirty-4k`、4 KiB Image、模块和设备树产物。
4. **做成 ROM 组件**：保留原 boot v4 头部和原 vendor_boot 的 fstab、bootconfig、DTB；将 6.12 Image 放入 `boot.img`，将 6.12 early modules 放入 `vendor_boot.img`，用 6.12 DLKM 镜像替换原 super 中的 `system_dlkm`/`vendor_dlkm`。不把 6.6 `.ko` 混入 6.12。
5. **处理 DTBO**：原 DTBO 表共 76 项，只替换零基索引 51（第 52 项）的 elden overlay。该项偏移不变，原大小 467,344 字节，6.12 overlay 为 466,958 字节；零基索引 50 是另一 SKU1 overlay，不能替换。
6. **重建 AVB 和 9008 包**：沿用原 RSA4096 根公钥、chain descriptor 和 rollback 配置，重建变更镜像的 hash descriptor。候选保留原六个 rawprogram XML 和所有未改动分区，更新 `SHA256SUMS.txt`。
7. **完成静态验收**：80 项清单、101 个 program 条目、镜像尺寸和 XML 引用、boot/vendor_boot/dtbo/init_boot/recovery/vbmeta_system AVB、顶层 vbmeta chain/hash descriptor、super 三个 metadata slot 均通过。

## 关键经验

- **6.6 到 6.12 不是只换版本字符串**：`CONFIG_MODVERSIONS`、`__versions`、vermagic、厂商模块和 DTB/DTBO 必须成套匹配。旧 `.ko` 不能作为缺项补丁。
- **组件构建不等于 ROM 可启动**：Actions 可以证明内核和模块能编译、设备树格式可解析，但不能证明 ColorOS HAL、VINTF、早期挂载和真实硬件兼容。
- **原包的分区约束必须优先**：boot/vendor_boot 只能使用 96 MiB，dtbo 32 MiB，vbmeta 64 KiB，super 必须保持 23,622,320,128 字节和原 metadata slot 布局。
- **DTBO 不能按“第几个大文件”猜**：要按表索引、offset、board-id、root model 和 msm-id 确认目标 overlay；本项目正确目标是零基索引 51。
- **AVB 描述符必须跟着实际镜像变更**：替换 `init_boot`、vendor_boot 或 dtbo 后必须重新计算对应 hash；仅验证签名本身不够。
- **9008 包的静态通过仍需回滚路径**：测试前保留完整原包，先确认原包能救援，再进行候选刷写；失败时用同一 XML 回刷原包。
- **候选必须与原包隔离**：组装器现在校验基线 SHA256、校验 XML 分区容量并复制文件，不使用硬链接，避免后续编辑候选意外修改原包。

## 最终验收顺序

1. 从设备提取与当前槽位对应的原版和 KSU patched `init_boot`，保留原始救援包。
2. 使用项目 `avb签名工具` 的 RSA4096 密钥签名 patched `init_boot`。
3. 将签名后的 `init_boot` 替换进 6.12 候选，并重建 `vbmeta.img` 的 `init_boot` hash descriptor；重新跑 AVB、SHA256、XML 和 super 校验。
4. 进入 9008，先确认 Firehose 识别和分区写入完成，再刷候选包。
5. 记录启动日志，依次确认早期 kernel、UFS、动态分区、init、ADB、显示/触控和 Android framework。
6. 验证 KSU、Wi-Fi/蓝牙、音频、相机、USB、充电、热控、休眠唤醒和 recovery。
7. 只有在上述步骤通过后，才把候选升级为“可用 6.12 包”；在此之前应称为“静态检查候选包”。

## 证据链

- **E-001 原包基线**：`c16-300-9008-V17.6` 的 boot/vendor_boot/super/DTBO 和模块/VINTF 检查，复现入口见 `tools/inspect_boot.py`、`tools/inspect_super.py`。
- **E-002 Actions 构建**：run `38936781318`，6.12.81、4 KiB、模块和 DT 产物检查通过，详见 `docs/kernel-upgrade/actions-build.md`。
- **E-003 候选静态验收**：`.work/9008-candidate-c16-6.12` 的 SHA256、AVB、XML、DTBO 和 super 验收，详见 `docs/kernel-upgrade/9008-candidate.md`。
- **E-004 用户设备实测**：锁定 BL 下原版 KSU patched `init_boot` 签名后可以开机；这是独立证据，不替代 6.12 候选真机验证。

### P-001 目标路径

- `path_type=solve`
- `start=原始 c16-300-9008-V17.6`
- `goal=6.12 9008 包正常开机，并通过锁定 BL 下 KSU patched init_boot 验证`
- `steps=源码锁定与 Actions 构建（E-002）→原包组件集成和静态候选（E-003）→KSU init_boot 签名并更新 AVB→9008 真机刷写与硬件验收（E-004 仅支持原版 init_boot 先例）`
- `residual_risks=Oplus 模块缺失、recovery 加载表不完整、KSU init_boot 尚未集成、设备尚未实刷`
