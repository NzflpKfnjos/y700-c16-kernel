#!/usr/bin/env python3
"""Read-only Android boot v3/v4 / vendor_boot v4 kernel preflight.

Reads source images; writes only to a separate output directory. No flashing,
module loading, signature bypass, or image repacking is performed.
Requires Python 3 and the lz4 CLI for compressed ramdisks.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def align(value, page=4096):
    return (value + page - 1) // page * page


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def cpio_entries(data):
    """Read newc archives without extracting paths or following symlinks."""
    offset = 0
    while offset < len(data):
        if data[offset:offset + 6] not in (b"070701", b"070702"):
            raise ValueError(f"Unsupported/truncated cpio at {offset}")
        header = [int(data[offset + 6 + i * 8:offset + 14 + i * 8], 16)
                  for i in range(13)]
        size, name_size = header[6], header[11]
        name_start = offset + 110
        payload = align(name_start + name_size, 4)
        end = payload + size
        if not name_size or end > len(data):
            raise ValueError("Truncated cpio entry")
        name = data[name_start:name_start + name_size - 1].decode(errors="replace")
        offset = align(end, 4)
        if name == "TRAILER!!!":
            while offset < len(data) and data[offset] == 0:
                offset += 1
            continue
        yield name, data[payload:end]


def inspect_module(data):
    if data[:6] != b"\x7fELF\x02\x01":
        return {"format_error": "Expected ELF64 little endian"}
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    entry_size, count, names_index = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, section_offset + i * entry_size)
                for i in range(count)]
    name_section = sections[names_index]
    names = data[name_section[4]:name_section[4] + name_section[5]]
    fields, undefined, version_count = {}, [], 0
    for section in sections:
        offset, size = section[4:6]
        name = names[section[0]:names.index(b"\0", section[0])]
        if name == b".modinfo":
            for field in data[offset:offset + size].split(b"\0"):
                if b"=" in field:
                    key, value = field.split(b"=", 1)
                    fields.setdefault(key.decode(errors="replace"), []).append(
                        value.decode(errors="replace"))
        elif name == b"__versions":
            version_count = size // 64
        elif section[1] == 2:  # SHT_SYMTAB
            strings_section = sections[section[6]]
            strings = data[strings_section[4]:strings_section[4] + strings_section[5]]
            for cursor in range(offset, offset + size, section[9]):
                symbol, _, _, index, _, _ = struct.unpack_from("<IBBHQQ", data, cursor)
                if symbol and index == 0:
                    undefined.append(strings[symbol:strings.index(b"\0", symbol)].decode())
    return {key: fields.get(key, []) for key in ("vermagic", "depends", "name", "srcversion")} | {
        "versioned_symbol_count": version_count,
        "undefined_symbol_count": len(undefined), "undefined_symbol_sample": undefined[:20]}


def inspect_cpio(data):
    files, modules, texts = [], [], {}
    for name, payload in cpio_entries(data):
        files.append({"name": name, "size": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()})
        if name.endswith(".ko"):
            modules.append({"path": name, "size": len(payload), **inspect_module(payload)})
        elif 0 < len(payload) < 200000 and (
            "fstab" in name or "modules." in name or name.endswith(".rc")
        ):
            texts[name] = payload.decode(errors="replace")
    return {"file_count": len(files), "module_count": len(modules),
            "files": files, "modules": modules, "texts": texts}


def inspect_dtbs(data):
    trees, offset = [], 0
    while offset + 40 <= len(data):
        tree = data[offset:]
        magic, size, structure, strings_offset, _, _, _, _, strings_size, structure_size = (
            struct.unpack_from(">10I", tree))
        if magic != 0xD00DFEED or size > len(tree):
            raise ValueError(f"Invalid concatenated FDT at {offset}")
        tree = tree[:size]
        strings = tree[strings_offset:strings_offset + strings_size]
        cursor, depth, props = structure, -1, {}
        while cursor + 4 <= structure + structure_size:
            token = struct.unpack_from(">I", tree, cursor)[0]
            cursor += 4
            if token == 1:
                cursor = align(tree.index(b"\0", cursor) + 1, 4)
                depth += 1
            elif token == 2:
                depth -= 1
            elif token == 3:
                length, name_offset = struct.unpack_from(">II", tree, cursor)
                cursor += 8
                value = tree[cursor:cursor + length]
                cursor = align(cursor + length, 4)
                key = strings[name_offset:strings.index(b"\0", name_offset)].decode()
                if depth == 0:
                    props[key] = ([x.decode(errors="replace")
                                   for x in value.rstrip(b"\0").split(b"\0")]
                                  if key in ("model", "compatible") else value.hex())
            elif token == 4:
                continue
            elif token == 9:
                break
            else:
                raise ValueError(f"Invalid FDT token {token}")
        trees.append({"offset": offset, "size": size, "root_properties": props})
        offset += size
    return trees


def inspect(images, out):
    manifest = {}
    manifest_path = images.parent / "SHA256SUMS.txt"
    if manifest_path.is_file():
        for line in manifest_path.read_text().splitlines():
            if line.strip():
                digest, name = line.split(maxsplit=1)
                manifest[name.strip().lstrip("*")] = digest
    facts, ramdisks = {}, {}
    for name in ("boot", "init_boot", "vendor_boot", "dtbo", "vbmeta", "vbmeta_system"):
        path = images / (name + ".img")
        if not path.is_file():
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        item = {"size": len(data), "sha256": digest}
        expected = manifest.get("images/" + path.name)
        if expected:
            item["manifest_match"] = digest == expected
        if name in ("boot", "init_boot"):
            if data[:8] != b"ANDROID!":
                raise ValueError(f"Invalid {name} magic")
            version = struct.unpack_from("<I", data, 40)[0]
            if version not in (3, 4):
                raise ValueError(f"Unsupported boot header {version}")
            kernel_size, ramdisk_size, _, header_size = struct.unpack_from("<4I", data, 8)
            item.update(header_version=version, kernel_size=kernel_size,
                        ramdisk_size=ramdisk_size, header_size=header_size)
            kernel = data[4096:4096 + kernel_size]
            item["kernel_versions"] = [x.decode() for x in re.findall(
                rb"Linux version [\x20-\x7e]{1,400}", kernel)[:2]]
            if kernel_size:
                (out / "Image").write_bytes(kernel)
                start = kernel.find(b"IKCFG_ST")
                if start >= 0:
                    end = kernel.index(b"IKCFG_ED", start)
                    config = gzip.decompress(kernel[start + 8:end])
                    (out / "kernel.config").write_bytes(config)
                    item["config_size"] = len(config)
            if ramdisk_size:
                start = 4096 + align(kernel_size)
                ramdisks[name] = data[start:start + ramdisk_size]
        elif name == "vendor_boot":
            if data[:8] != b"VNDRBOOT":
                raise ValueError("Invalid vendor_boot magic")
            version, page = struct.unpack_from("<II", data, 8)
            if version != 4:
                raise ValueError(f"Unsupported vendor_boot header {version}")
            ramdisk_size = struct.unpack_from("<I", data, 24)[0]
            header_size, dtb_size = struct.unpack_from("<II", data, 2096)
            table_size, count, entry_size, bootconfig_size = struct.unpack_from("<4I", data, 2112)
            start = align(header_size, page)
            dtb_start = start + align(ramdisk_size, page)
            table_start = dtb_start + align(dtb_size, page)
            config_start = table_start + align(table_size, page)
            dtb = data[dtb_start:dtb_start + dtb_size]
            (out / "dtb").write_bytes(dtb)
            save_json(out / "dtb-facts.json", inspect_dtbs(dtb))
            item.update(header_version=version, page_size=page,
                        ramdisk_size=ramdisk_size, dtb_size=dtb_size,
                        bootconfig=data[config_start:config_start + bootconfig_size].decode(),
                        ramdisk_entries=[])
            ramdisks["vendor-full"] = data[start:start + ramdisk_size]
            for index in range(count):
                cursor = table_start + index * entry_size
                size, relative, kind = struct.unpack_from("<III", data, cursor)
                ramdisks[f"vendor-{index}"] = data[start + relative:start + relative + size]
                item["ramdisk_entries"].append({"index": index, "size": size,
                    "offset": relative, "type": kind,
                    "name": data[cursor + 12:cursor + 44].split(b"\0")[0].decode()})
        elif name.startswith("vbmeta") and data[:4] == b"AVB0":
            item.update(avb_algorithm=struct.unpack_from(">I", data, 28)[0],
                        avb_flags=struct.unpack_from(">I", data, 120)[0],
                        avb_release=data[128:176].split(b"\0")[0].decode())
        elif name == "dtbo":
            header = struct.unpack_from(">8I", data)
            if header[0] != 0xD7B7AB1E:
                raise ValueError("Invalid DTBO magic")
            item.update(entry_count=header[4], format_version=header[7])
        facts[name] = item
    ramdisk_facts = {}
    for name, compressed in ramdisks.items():
        source = out / (name + "-ramdisk.lz4")
        source.write_bytes(compressed)
        if compressed[:6] in (b"070701", b"070702"):
            decoded = compressed
        else:
            result = subprocess.run(["lz4", "-d", "-c", str(source)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                ramdisk_facts[name] = {
                    "decode_error": result.stderr.decode(errors="replace").strip(),
                    "compressed_size": len(compressed),
                    "decoded_prefix_size": len(result.stdout)}
                continue
            decoded = result.stdout
        ramdisk_facts[name] = inspect_cpio(decoded)
    save_json(out / "boot-facts.json", facts)
    save_json(out / "ramdisk-facts.json", ramdisk_facts)
    print(json.dumps({"boot": facts.get("boot"), "ramdisks": {
        k: ({"files": v["file_count"], "modules": v["module_count"],
            "vermagic": sorted({s for m in v["modules"] for s in m["vermagic"]})}
            if "modules" in v else v)
        for k, v in ramdisk_facts.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    images, out = args.images.resolve(), args.out.resolve()
    if out.is_relative_to(images) or images.is_relative_to(out):
        parser.error("Output and source image directories must not overlap")
    out.mkdir(parents=True, exist_ok=True)
    inspect(images, out)
