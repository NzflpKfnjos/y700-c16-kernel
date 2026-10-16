#!/usr/bin/env python3
"""Stream raw logical partition images from an Android super.img metadata slot."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from inspect_super import Super


CHUNK_SIZE = 4 * 1024 * 1024


def extract(image: Path, out: Path, slot: int, selected: list[str] | None = None):
    image = image.resolve()
    out = out.resolve()
    source_root = image.parent.parent
    if source_root == out or source_root in out.parents:
        raise ValueError("Output directory must be outside the source package")
    if out.exists():
        raise FileExistsError(f"Output directory already exists: {out}")

    super_image = Super(image, slot=slot)
    names = selected or list(super_image.partitions)
    unknown = sorted(set(names) - set(super_image.partitions))
    if unknown:
        raise ValueError(f"Partitions are absent from metadata slot {slot}: {unknown}")
    if len(set(names)) != len(names):
        raise ValueError("Partition names must be unique")

    out.mkdir(parents=True, exist_ok=False)
    manifest = {
        "source_image": str(image),
        "metadata_slot": slot,
        "source_image_size": image.stat().st_size,
        "partitions": [],
    }
    zeroes = bytes(CHUNK_SIZE)

    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_]+", name):
            raise ValueError(f"Unsafe partition name: {name!r}")
        partition = super_image.partitions[name]
        destination = out / f"{name}.img"
        digest = hashlib.sha256()
        written = 0
        with destination.open("xb") as target:
            for extent in partition["extents"]:
                if extent["target_source"] != 0:
                    raise ValueError(f"Unsupported block device for {name}: {extent}")
                remaining = extent["num_sectors"] * 512
                source_offset = extent["target_data"] * 512
                while remaining:
                    length = min(CHUNK_SIZE, remaining)
                    if extent["target_type"] == 0:
                        chunk = super_image.read(source_offset, length)
                        source_offset += length
                    elif extent["target_type"] == 1:
                        chunk = zeroes[:length]
                    else:
                        raise ValueError(f"Unsupported extent type for {name}: {extent}")
                    target.write(chunk)
                    digest.update(chunk)
                    written += length
                    remaining -= length
            if written != partition["size"]:
                raise ValueError(f"Extracted size mismatch for {name}: {written} != {partition['size']}")

        manifest["partitions"].append({
            "name": name,
            "path": destination.name,
            "size": written,
            "sha256": digest.hexdigest(),
            "extent_count": partition["num_extents"],
        })

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), "slot": slot,
                      "partition_count": len(manifest["partitions"]),
                      "partitions": manifest["partitions"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--slot", type=int, default=0)
    parser.add_argument("--partitions", nargs="+",
                        help="Optional list; defaults to every partition in the slot")
    args = parser.parse_args()
    extract(args.image, args.out, args.slot, args.partitions)


if __name__ == "__main__":
    main()
