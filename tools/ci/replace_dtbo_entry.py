#!/usr/bin/env python3
"""Replace one DTBO table entry in an AVB-footer-free image without moving peers."""

import argparse
import hashlib
import json
from pathlib import Path
import struct


DTBO_MAGIC = 0xD7B7AB1E


def entries(data):
    if len(data) < 32:
        raise ValueError("DTBO image is shorter than its header")
    magic, total_size, header_size, entry_size, count, table_offset, page_size, version = (
        struct.unpack_from(">8I", data, 0))
    if magic != DTBO_MAGIC or version != 0:
        raise ValueError("Expected DTBO version 0 image")
    if header_size != 32 or entry_size < 32 or total_size > len(data):
        raise ValueError("Invalid DTBO header dimensions")
    if table_offset < header_size or table_offset + count * entry_size > total_size:
        raise ValueError("DTBO entry table is out of bounds")
    result = []
    for index in range(count):
        table_pos = table_offset + index * entry_size
        size, offset, ident, revision, *custom = struct.unpack_from(">8I", data, table_pos)
        if offset < header_size or offset + size > total_size:
            raise ValueError(f"DTBO entry {index} is out of bounds")
        result.append({"index": index, "table_pos": table_pos, "size": size,
                       "offset": offset, "id": ident, "rev": revision,
                       "custom": custom})
    ordered = sorted(result, key=lambda item: item["offset"])
    for left, right in zip(ordered, ordered[1:]):
        if left["offset"] + left["size"] > right["offset"]:
            raise ValueError(f"Overlapping DTBO entries {left['index']} and {right['index']}")
    return {"total_size": total_size, "count": count, "page_size": page_size,
            "entries": result, "ordered": ordered}


def replace(image: Path, payload: Path, output: Path, index: int):
    image, payload, output = image.resolve(), payload.resolve(), output.resolve()
    if output in (image, payload):
        raise ValueError("Output must be different from both inputs")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    original = image.read_bytes()
    replacement = payload.read_bytes()
    info = entries(original)
    if index < 0 or index >= info["count"]:
        raise ValueError(f"Entry index is outside the table: {index}")
    target = info["entries"][index]
    next_offset = min((item["offset"] for item in info["ordered"]
                       if item["offset"] > target["offset"]), default=info["total_size"])
    if len(replacement) > target["size"]:
        raise ValueError(f"Replacement is larger than entry {index}: "
                         f"{len(replacement)} > {target['size']}")
    if target["offset"] + len(replacement) > next_offset:
        raise ValueError("Replacement would overlap the next DTBO payload")

    updated = bytearray(original[:info["total_size"]])
    updated[target["offset"]:target["offset"] + target["size"]] = bytes(target["size"])
    updated[target["offset"]:target["offset"] + len(replacement)] = replacement
    struct.pack_into(">I", updated, target["table_pos"], len(replacement))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(updated)

    print(json.dumps({"output": str(output), "sha256": hashlib.sha256(updated).hexdigest(),
                      "entry_count": info["count"], "entry_index": index,
                      "entry_old_size": target["size"], "entry_new_size": len(replacement),
                      "entry_id": target["id"], "entry_rev": target["rev"],
                      "entry_custom": target["custom"],
                      "entry_old_sha256": hashlib.sha256(original[
                          target["offset"]:target["offset"] + target["size"]]).hexdigest(),
                      "entry_new_sha256": hashlib.sha256(replacement).hexdigest(),
                      "other_entries_relocated": False,
                      "partition_size": 33554432,
                      "requires_avb_footer": True,
                      "candidate_only": True,
                      "flashable_or_boot_validated": False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True,
                        help="DTBO image with its AVB footer already removed")
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    replace(args.image, args.payload, args.output, args.index)


if __name__ == "__main__":
    main()
