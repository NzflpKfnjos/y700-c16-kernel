# super 镜像的只读检查

运行目录：`/Users/a77/Desktop/git/y700_c16`。源文件只以 `rb` / dump.erofs 的只读方式打开，没有全量解包。

```sh
python3 tools/inspect_super.py c16-300-9008-V17.6/images/super.img --collect
```

仅列出 LP 元数据与分区格式、不读取选中文件：

```sh
python3 tools/inspect_super.py c16-300-9008-V17.6/images/super.img
```

默认输出 `.work/super-inspection/`。`lp-metadata.json` 是 slot 0 的分区/extents；几何、当前 header、tables 的 SHA-256 字段已核验。没有核验所有 metadata slots/备份副本。

`--collect` 使用隔离放置的 `erofs-utils/1.9.4/bin/dump.erofs`，可通过 `--erofs-tool /absolute/path/to/dump.erofs` 更换。该 macOS arm64 Homebrew bottle 的来源、SHA-256、依赖路径见 `tool-provenance.json`。没有全局安装新软件。脚本为 bottle 设置已有的 `/opt/homebrew/opt/lz4/lib` 与 `/opt/homebrew/opt/xz/lib` 动态库目录。

脚本对每一条待读取路径检查所有中间目录、inode 与文件数据的范围。只有这些范围都落在第一个 LP linear extent 内时，才允许使用 dump.erofs 的 `--offset` 随机访问；跨 extent 的其他文件会拒绝。选中证据在本包均通过此范围检查。

本次提取 19 个选中文件，合计 8,588,724 bytes；包含 5 个 .ko 样本、模块加载/依赖清单、属性与 VINTF XML。模块总数来自两个完整目录列表：system_dlkm 96 个，vendor_dlkm 302 个。没有遍历其余 .ko 的 vermagic，没有声明整个文件系统校验成功。`selected-files.json` 记录每个输出的 SHA-256 与 .modinfo；`summary.json` 记录属性、VINTF 与目录计数。

LP reader 的 bytes_read 统计不包括外部 dump.erofs 的读取量。
