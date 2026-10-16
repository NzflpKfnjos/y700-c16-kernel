# 9008 候选包

当前候选目录：`/Users/a77/Desktop/git/y700_c16/.work/9008-candidate-c16-6.12`

它以 `c16-300-9008-V17.6` 为唯一基线，保留原始 9008 目录结构、`rawprogram0.xml` 到 `rawprogram5.xml`、Firehose 引导文件和未改动的其他分区镜像。候选只替换以下五个镜像：

- `boot.img`：保留原 boot v4 头部，替换为 `6.12.81-android16-6-maybe-dirty-4k` ARM64 Image，并按原 ROM RSA4096 AVB 密钥签名。
- `vendor_boot.img`：使用 6.12 模块，保留原 ROM fstab、bootconfig 和 DTB，并按 96 MiB 分区大小重新生成和签名。
- `dtbo.img`：保留原 76 项表，只替换零基表索引 51（第 52 项）的 elden 6.12 overlay；零基索引 50 是另一 SKU1 overlay，未改动。
- `super.img`：保留原 15 个逻辑分区和三个 metadata slot，替换 `system_dlkm`、`vendor_dlkm` 为本次 6.12 构建的 ext4 镜像。
- `vbmeta.img`：保留原 AVB 根公钥、rollback/index 配置，并重建 `dtbo`、原版 `init_boot`、`vendor_boot` 描述符。

## 静态验收

- 候选 `SHA256SUMS.txt` 的 80 项文件全部匹配。
- 六个 rawprogram XML 与原包字节一致，全部引用文件存在，所有写入大小不超过 XML 的分区分配。
- `boot`、`vendor_boot`、`dtbo`、`init_boot`、`recovery`、`vbmeta_system` 的 AVB footer/hash 验证通过。
- 顶层 `vbmeta` 的 RSA4096 签名、`boot`/`recovery`/`vbmeta_system` 链描述符，以及 `dtbo`/`init_boot`/`vendor_boot` hash 描述符验证通过。
- `super.img` 三个 metadata slot 的结构和分区数据哈希通过，大小为 23,622,320,128 字节。

## 已知限制

这是**静态检查过的 9008 候选包**，没有在 Y700 四代真机上用 9008/Firehose 实刷，也没有启动日志或硬件功能验证。6.12 构建中没有原 ROM 的 5 个 Oplus 模块：`oplus_network_data_module`、`oplus_network_linkpower_module`、`oplus_network_tuning`、`oplus_network_vnet`、`oplus_sys_stability_helper`。原 normal 加载表还有 16 个待审查的非 sun 平台模块，recovery 加载表当前沿用了 98 项 normal 6.12 列表，而原 ROM recovery 列表为 321 项。

当前候选仍使用原版 `init_boot.img`，没有集成 KSU 修补的 `init_boot`。最终目标要求在取得实际 KSU patched `init_boot` 后，用项目 RSA4096 工具签名，将它作为同一 AVB 链的 `init_boot` 替换镜像，并重新生成/验证 `vbmeta.img` 的 `init_boot` hash 描述符，再进行真机测试。

不要把原 6.6 `.ko` 混入 6.12 镜像；它们带有不同的 vermagic 和符号版本。首次测试前应保留完整的原始 `c16-300-9008-V17.6` 包，并准备使用原包的同一组 XML 回刷。候选包失败时，优先回刷原包恢复设备。
