#!/usr/bin/env python3
"""Validate the pinned sun/elden component build's DT artifacts."""

import hashlib
from pathlib import Path
import struct


BASE_DTBS = tuple(sorted((
    "sun.dtb", "sun-v2.dtb", "sun-tp.dtb", "sun-tp-v2.dtb",
    "sunp.dtb", "sunp-v2.dtb", "sunp-tp.dtb", "sunp-tp-v2.dtb",
)))
TECHPACK_DTBOS = tuple(sorted((
    "sun-audio.dtbo", "sun-camera.dtbo", "sun-dsp.dtbo",
    "sun-eva-v2.dtbo", "sun-eva.dtbo", "sun-fingerprint.dtbo",
    "sun-gpu.dtbo", "sun-hw-fence.dtbo", "sun-ipa.dtbo",
    "sun-mmrm-test.dtbo", "sun-mmrm.dtbo", "sun-nfc.dtbo",
    "sun-synx.dtbo", "sun-v2-gpu.dtbo", "sun-vidc-v2.dtbo",
    "sun-vidc.dtbo",
)))
BOARD_DTBO = "sun-elden-overlay.dtbo"
_FDT_MAGIC = 0xD00DFEED
_DT_TABLE_MAGIC = 0xD7B7AB1E
_MAX_ARTIFACT_SIZE = 128 * 1024 * 1024


def _fdt_header(data):
    """Check modern FDT header/block bounds, not binding semantics."""
    if len(data) < 40:
        raise ValueError("truncated FDT header")
    magic, total, structure, strings, reserve, version, compatible, _, strings_size, structure_size = (
        struct.unpack_from(">10I", data))
    if magic != _FDT_MAGIC:
        raise ValueError("invalid FDT magic")
    if total != len(data):
        raise ValueError(f"FDT totalsize {total} differs from payload size {len(data)}")
    if version < 17 or compatible > 17 or compatible > version:
        raise ValueError(f"unsupported FDT version/compatibility {version}/{compatible}")
    if structure % 4 or reserve % 8 or reserve < 40:
        raise ValueError("invalid FDT block alignment or reserve offset")
    blocks = [("structure", structure, structure_size), ("strings", strings, strings_size)]
    for name, offset, size in blocks:
        if offset < 40 or offset > total or size > total - offset:
            raise ValueError(f"FDT {name} block exceeds payload bounds")
    if structure_size < 12 or structure_size % 4:
        raise ValueError("invalid FDT structure block size")
    if max(structure, strings) < min(structure + structure_size, strings + strings_size):
        raise ValueError("overlapping FDT structure and strings blocks")
    reserve_end = reserve
    while reserve_end + 16 <= total:
        address, size = struct.unpack_from(">QQ", data, reserve_end)
        reserve_end += 16
        if address == size == 0:
            break
    else:
        raise ValueError("unterminated FDT memory reserve map")
    for name, offset, size in blocks:
        if max(reserve, offset) < min(reserve_end, offset + size):
            raise ValueError(f"FDT memory reserve map overlaps {name} block")
    if data[structure:structure + 4] != b"\x00\x00\x00\x01" or (
            data[structure + structure_size - 4:structure + structure_size] != b"\x00\x00\x00\x09"):
        raise ValueError("FDT structure has invalid begin/end tokens")
    return {"total_size": total, "version": version,
            "last_compatible_version": compatible, "structure_size": structure_size,
            "strings_size": strings_size}


def inspect_device_trees(dist: Path) -> dict:
    """Return errors and static DT metadata; never infer runtime selection."""
    dist = Path(dist)
    errors, raw, payloads = [], {}, {}
    result = {"errors": errors, "raw_artifacts": raw,
              "base_dtb_names": list(BASE_DTBS), "techpack_dtbo_names": list(TECHPACK_DTBOS),
              "board_overlay_name": BOARD_DTBO,
              "elden_overlay_runtime_selection_verified": False,
              "techpack_overlays_merged": False,
              "limitations": "Static FDT/header and packaging checks only; techpack merging, "
                             "ROM integration and device selection remain unverified."}

    def read(name):
        candidates = sorted(path for path in dist.rglob(name) if path.is_file())
        if len(candidates) != 1:
            errors.append(f"Expected one device-tree artifact {name}, found {len(candidates)}")
            return None
        path = candidates[0]
        try:
            if path.stat().st_size > _MAX_ARTIFACT_SIZE:
                raise ValueError("artifact exceeds 128 MiB inspection limit")
            return path.read_bytes()
        except (OSError, ValueError) as exc:
            errors.append(f"Cannot read {path.relative_to(dist)}: {exc}")
            return None

    for name in BASE_DTBS + TECHPACK_DTBOS + (BOARD_DTBO,):
        data = read(name)
        if data is None:
            continue
        payloads[name] = data
        record = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        raw[name] = record
        try:
            record.update(_fdt_header(data))
            record["header_valid"] = True
        except (ValueError, struct.error) as exc:
            record["header_valid"] = False
            errors.append(f"Invalid raw FDT {name}: {exc}")

    dtb_image = read("dtb.img")
    concat = {"exact_sorted_base_concatenation": False, "fdt_count": 0}
    result["dtb_image"] = concat
    if dtb_image is not None:
        if all(name in payloads for name in BASE_DTBS):
            concat["exact_sorted_base_concatenation"] = (
                dtb_image == b"".join(payloads[name] for name in BASE_DTBS))
            if not concat["exact_sorted_base_concatenation"]:
                errors.append("dtb.img differs from the sorted concatenation of the 8 expected sun bases")
        offset = 0
        try:
            while offset < len(dtb_image):
                if offset + 8 > len(dtb_image):
                    raise ValueError("truncated concatenated FDT header")
                total = struct.unpack_from(">I", dtb_image, offset + 4)[0]
                if total < 40 or total > len(dtb_image) - offset:
                    raise ValueError("concatenated FDT totalsize exceeds remaining image")
                _fdt_header(dtb_image[offset:offset + total])
                offset += total
                concat["fdt_count"] += 1
            if concat["fdt_count"] != len(BASE_DTBS):
                raise ValueError(f"expected 8 FDT bases, found {concat['fdt_count']}")
        except (ValueError, struct.error) as exc:
            errors.append(f"Invalid dtb.img: {exc}")

    dtbo_image = read("dtbo.img")
    table = {"board_payload_matches": False}
    result["dtbo_image"] = table
    if dtbo_image is not None:
        try:
            if len(dtbo_image) < 32:
                raise ValueError("truncated Android DT table header")
            magic, total, header_size, entry_size, count, entries_offset, page_size, version = (
                struct.unpack_from(">8I", dtbo_image))
            table.update({"total_size": total, "entry_count": count, "version": version,
                          "page_size": page_size})
            if magic != _DT_TABLE_MAGIC:
                raise ValueError("invalid Android DT table magic")
            if version != 0 or header_size != 32 or entry_size != 32:
                raise ValueError("unexpected DT table version/header/entry size for mkdtimg create")
            if total < header_size or total > len(dtbo_image):
                raise ValueError("DT table totalsize exceeds image bounds")
            if count != 1:
                raise ValueError(f"expected exactly one elden overlay entry, found {count}")
            if entries_offset < header_size or entries_offset > total - entry_size:
                raise ValueError("DT entry table exceeds image bounds")
            size, offset = struct.unpack_from(">2I", dtbo_image, entries_offset)
            if size < 40 or offset < entries_offset + entry_size or offset > total or size > total - offset:
                raise ValueError("DT overlay payload exceeds image bounds or overlaps the table")
            payload = dtbo_image[offset:offset + size]
            _fdt_header(payload)
            table.update({"payload_offset": offset, "payload_size": size})
            table["board_payload_matches"] = (
                BOARD_DTBO in payloads and payload == payloads[BOARD_DTBO])
            if not table["board_payload_matches"]:
                errors.append("dtbo.img payload differs from sun-elden-overlay.dtbo")
        except (ValueError, struct.error) as exc:
            errors.append(f"Invalid dtbo.img: {exc}")
    result["status"] = "device_tree_checks_failed" if errors else "device_tree_checks_passed"
    return result
