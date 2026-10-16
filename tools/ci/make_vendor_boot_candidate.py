#!/usr/bin/env python3
"""Build an experimental 6.12-only vendor_boot candidate from ROM and CI inputs.

The candidate preserves the ROM DTB, fstab, and bootconfig to keep its existing
DTBO pairing. It does not preserve any stock 6.6 modules or module metadata.
The build's normal module list is reused for recovery because no 6.12 recovery
list is available; recovery coverage is therefore incomplete and unverified.
The output is unsigned and is not a validated flash image.
"""

import argparse
import gzip
import hashlib
import struct
import subprocess
from pathlib import Path


PAGE = 4096
VENDOR_BOOT_HEADER_SIZE = 2128
PARTITION_SIZE = 100663296


def align(value, boundary=4):
    return (value + boundary - 1) // boundary * boundary


def cpio_read(data):
    entries = {}
    order = []
    offset = 0
    while offset < len(data):
        if data[offset:offset + 6] not in (b"070701", b"070702"):
            raise ValueError(f"invalid newc header at {offset}")
        fields = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16)
                  for i in range(13)]
        ino, mode, uid, gid, nlink, mtime, size, devmajor, devminor, rdevmajor, rdevminor, namesize, check = fields
        name_start = offset + 110
        name_end = name_start + namesize
        payload_start = align(name_end)
        payload_end = payload_start + size
        if name_end > len(data) or payload_end > len(data) or namesize < 1:
            raise ValueError("truncated newc entry")
        name = data[name_start:name_end - 1].decode("utf-8", "strict")
        payload = data[payload_start:payload_end]
        offset = align(payload_end)
        if name == "TRAILER!!!":
            break
        item = dict(ino=ino, mode=mode, uid=uid, gid=gid, nlink=nlink, mtime=mtime,
                    devmajor=devmajor, devminor=devminor, rdevmajor=rdevmajor,
                    rdevminor=rdevminor, check=check, payload=payload)
        if name not in entries:
            order.append(name)
        entries[name] = item
    return entries, order


def cpio_write(entries, order):
    out = bytearray()
    for name in order:
        item = entries[name]
        payload = item["payload"]
        name_bytes = name.encode("utf-8") + b"\0"
        fields = [0x070701, item.get("ino", 0), item["mode"], item["uid"], item["gid"], item["nlink"],
                  item["mtime"], len(payload), item["devmajor"], item["devminor"],
                  item["rdevmajor"], item["rdevminor"], len(name_bytes), item["check"]]
        out.extend(b"070701")
        out.extend(b"".join(f"{x:08x}".encode("ascii") for x in fields[1:]))
        out.extend(name_bytes)
        out.extend(b"\0" * (align(len(out), 4) - len(out)))
        out.extend(payload)
        out.extend(b"\0" * (align(len(out), 4) - len(out)))
    trailer = dict(ino=0, mode=0, uid=0, gid=0, nlink=1, mtime=0, devmajor=0,
                   devminor=0, rdevmajor=0, rdevminor=0, check=0, payload=b"")
    entries["TRAILER!!!"] = trailer
    name = b"TRAILER!!!\0"
    fields = [0x070701, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0]
    out.extend(b"070701")
    out.extend(b"".join(f"{x:08x}".encode("ascii") for x in fields[1:]))
    out.extend(name)
    out.extend(b"\0" * (align(len(out), 4) - len(out)))
    return bytes(out)


def decompress_ramdisk(data):
    if data.startswith(b"070701") or data.startswith(b"070702"):
        return data
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    result = subprocess.run(["lz4", "-d", "-c"], input=data,
                            stdout=subprocess.PIPE, check=True)
    return result.stdout


def compress_lz4(data):
    result = subprocess.run(["lz4", "-z", "-c"], input=data,
                            stdout=subprocess.PIPE, check=True)
    return result.stdout


def extract_vendor_boot(path):
    data = path.read_bytes()
    if data[:8] != b"VNDRBOOT":
        raise ValueError(f"not vendor_boot: {path}")
    version, page = struct.unpack_from("<II", data, 8)
    if version != 4 or page != PAGE:
        raise ValueError("only vendor_boot v4 with 4096-byte pages is supported")
    ramdisk_size = struct.unpack_from("<I", data, 24)[0]
    header_size, dtb_size = struct.unpack_from("<II", data, 2096)
    table_size, count, entry_size, bootconfig_size = struct.unpack_from("<4I", data, 2112)
    start = align(header_size, page)
    dtb_start = start + align(ramdisk_size, page)
    table_start = dtb_start + align(dtb_size, page)
    config_start = table_start + align(table_size, page)
    return dict(data=data, header=data[:header_size], ramdisk=data[start:start + ramdisk_size],
                dtb=data[dtb_start:dtb_start + dtb_size],
                bootconfig=data[config_start:config_start + bootconfig_size],
                page=page, header_size=header_size, table_size=table_size,
                count=count, entry_size=entry_size, bootconfig_size=bootconfig_size)


def make_candidate(old_path, new_path, output):
    old_path = old_path.resolve()
    new_path = new_path.resolve()
    output = output.resolve()
    if output in (old_path, new_path):
        raise ValueError("Output must be different from both vendor_boot inputs")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    old = extract_vendor_boot(old_path)
    new = extract_vendor_boot(new_path)
    old_entries, old_order = cpio_read(decompress_ramdisk(old["ramdisk"]))
    new_entries, new_order = cpio_read(decompress_ramdisk(new["ramdisk"]))

    if "first_stage_ramdisk/fstab.qcom" not in old_entries:
        raise ValueError("stock vendor ramdisk has no first_stage_ramdisk/fstab.qcom")

    version_dirs = [n for n in new_order if n.startswith("lib/modules/") and
                    n.endswith("/modules.load")]
    if len(version_dirs) != 1:
        raise ValueError(f"expected one versioned modules.load, found {version_dirs}")
    version_dir = version_dirs[0].rsplit("/", 1)[0]
    version = version_dir.rsplit("/", 1)[-1]
    module_paths = [n for n in new_order if n.startswith(version_dir + "/") and n.endswith(".ko")]
    inner_load = new_entries[version_dir + "/modules.load"]["payload"]
    load_lines = [line.strip() for line in inner_load.decode().splitlines() if line.strip()]
    if any(not line.startswith("extra/") for line in load_lines):
        raise ValueError("unexpected 6.12 modules.load path")
    module_set = {n for n in new_order if n.startswith(version_dir + "/") and n.endswith(".ko")}
    referenced_modules = {version_dir + "/" + line for line in load_lines}
    if referenced_modules != module_set:
        missing = sorted(module_set - referenced_modules)
        absent = sorted(referenced_modules - module_set)
        raise ValueError(f"6.12 module list and ramdisk differ: unlisted={missing}, absent={absent}")

    merged_entries = dict(new_entries)
    merged_order = list(new_order)
    for name in ("first_stage_ramdisk", "first_stage_ramdisk/fstab.qcom"):
        if name not in old_entries:
            raise ValueError(f"stock vendor ramdisk is missing {name}")
        if name not in merged_entries:
            merged_order.append(name)
        merged_entries[name] = old_entries[name]

    root_load = ("\n".join(f"{version}/{line}" for line in load_lines) + "\n").encode()
    load_item = dict(mode=0o100644, uid=0, gid=0, nlink=1, mtime=0,
                     devmajor=0, devminor=0, rdevmajor=0, rdevminor=0,
                     check=0, payload=root_load)
    for name in ("lib/modules/modules.load", "lib/modules/modules.load.recovery"):
        if name not in merged_entries:
            merged_order.append(name)
        merged_entries[name] = dict(load_item)

    cpio = cpio_write(merged_entries, merged_order)
    compressed = compress_lz4(cpio)
    dtb = old["dtb"]
    header = bytearray(old["header"])
    struct.pack_into("<I", header, 24, len(compressed))
    struct.pack_into("<II", header, 2096, old["header_size"], len(dtb))
    struct.pack_into("<4I", header, 2112, 108, 1, 108, len(old["bootconfig"]))
    table = bytearray(108)
    struct.pack_into("<III", table, 0, len(compressed), 0, 1)
    image = bytearray(header)
    image.extend(b"\0" * (align(len(image), PAGE) - len(image)))
    image.extend(compressed)
    image.extend(b"\0" * (align(len(image), PAGE) - len(image)))
    image.extend(dtb)
    image.extend(b"\0" * (align(len(image), PAGE) - len(image)))
    image.extend(table)
    image.extend(b"\0" * (align(len(image), PAGE) - len(image)))
    image.extend(old["bootconfig"])
    if len(image) > PARTITION_SIZE:
        raise ValueError(f"vendor_boot candidate exceeds the {PARTITION_SIZE}-byte partition")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(image)
    print({"output": str(output), "sha256": hashlib.sha256(image).hexdigest(),
           "cpio_size": len(cpio), "ramdisk_compressed_size": len(compressed),
           "dtb_size": len(dtb), "bootconfig_size": len(old["bootconfig"]),
           "new_module_count": len(module_paths),
           "stock_6_6_module_count_removed": sum(1 for n in old_order if n.endswith(".ko")),
           "stock_module_metadata_removed": sorted(n for n in old_order
               if n.startswith("lib/modules/") and n.count("/") == 2 and n.rsplit("/", 1)[-1].startswith("modules.")),
           "recovery_load_list_reuses_normal_6_12_list": True,
           "partition_size": PARTITION_SIZE,
           "preserves_rom_dtb_for_original_dtbo": True,
           "requires_avb_footer": True, "candidate_only": True,
           "flashable_or_boot_validated": False})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-vendor-boot", type=Path, required=True)
    ap.add_argument("--new-vendor-boot", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    make_candidate(args.old_vendor_boot, args.new_vendor_boot, args.output)


if __name__ == "__main__":
    main()
