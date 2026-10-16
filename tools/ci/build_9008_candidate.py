#!/usr/bin/env python3
"""Assemble an independent 9008 candidate from a complete source package."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


PARTITION_SIZES = {
    "boot.img": 100663296,
    "dtbo.img": 33554432,
    "super.img": 23622320128,
    "vendor_boot.img": 100663296,
    "vbmeta.img": 65536,
}


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def assemble(base: Path, output: Path, replacements: dict[str, Path]):
    base, output = base.resolve(), output.resolve()
    if output == base or base in output.parents:
        raise ValueError("Candidate directory must be outside the source package")
    if output.exists():
        raise FileExistsError(f"Candidate directory already exists: {output}")
    if set(replacements) != set(PARTITION_SIZES):
        raise ValueError(f"Exactly these replacements are required: {sorted(PARTITION_SIZES)}")

    for name, expected_size in PARTITION_SIZES.items():
        source = replacements[name].resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.stat().st_size != expected_size:
            raise ValueError(f"{name} has size {source.stat().st_size}, expected {expected_size}")
        if source == base / "images" / name:
            raise ValueError(f"Replacement points at the source package: {name}")
        replacements[name] = source

    source_images = base / "images"
    manifest_source = base / "SHA256SUMS.txt"
    if not source_images.is_dir() or not manifest_source.is_file():
        raise ValueError("Source must be the complete 9008 package with SHA256SUMS.txt")
    manifest_lines = manifest_source.read_text().splitlines()
    manifest = {}
    for line in manifest_lines:
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        relative = relative.strip().lstrip("*")
        if relative in manifest:
            raise ValueError(f"Duplicate checksum entry: {relative}")
        manifest[relative] = digest
    for name in PARTITION_SIZES:
        if f"images/{name}" not in manifest:
            raise ValueError(f"Source checksum manifest has no entry for images/{name}")

    for relative, expected in manifest.items():
        source = (base / relative).resolve()
        if base not in source.parents or not source.is_file():
            raise ValueError(f"Source checksum entry is missing or escapes the package: {relative}")
        if sha256(source) != expected:
            raise ValueError(f"Source checksum mismatch: {relative}")

    replacement_hashes = {name: sha256(path) for name, path in replacements.items()}

    shutil.copytree(base, output)
    for name, source in replacements.items():
        target = output / "images" / name
        temp = target.with_name(f".{name}.candidate-link")
        os.link(source, temp)
        os.replace(temp, target)

    updated_lines = []
    for line in manifest_lines:
        if not line.strip():
            updated_lines.append(line)
            continue
        _, relative = line.split(maxsplit=1)
        relative = relative.strip().lstrip("*")
        name = Path(relative).name if relative.startswith("images/") else ""
        digest = replacement_hashes[name] if name in replacements else manifest[relative]
        updated_lines.append(f"{digest}  {relative}")

    manifest_target = output / "SHA256SUMS.txt"
    manifest_temp = manifest_target.with_name(".SHA256SUMS.txt.candidate")
    with manifest_temp.open("x", encoding="utf-8") as destination:
        destination.write("\n".join(updated_lines) + "\n")
    os.replace(manifest_temp, manifest_target)

    rawprograms = sorted((output / "images").glob("rawprogram*.xml"))
    if not rawprograms:
        raise ValueError("No rawprogram XML files in candidate")
    references = set()
    capacities = {}
    for path in rawprograms:
        root = ET.parse(path).getroot()
        for program in root.iter("program"):
            filename = program.attrib.get("filename", "")
            if filename:
                references.add(filename)
                sectors = int(program.attrib.get("num_partition_sectors", "0"))
                sector_size = int(program.attrib.get("SECTOR_SIZE_IN_BYTES", "512"))
                allocation = sectors * sector_size
                capacities[filename] = min(capacities.get(filename, allocation), allocation)
    missing = sorted(name for name in references if not (output / "images" / name).is_file())
    if missing:
        raise ValueError(f"rawprogram XML references missing files: {missing}")
    oversized = sorted(name for name in references
                       if (output / "images" / name).stat().st_size > capacities[name])
    if oversized:
        raise ValueError(f"rawprogram XML allocations are too small: {oversized}")

    print({"candidate": str(output), "rawprogram_count": len(rawprograms),
           "referenced_image_count": len(references),
           "replacements": {name: {"size": path.stat().st_size,
                                    "sha256": replacement_hashes[name]}
                            for name, path in replacements.items()},
           "source_files_hardlinked": False,
           "original_package_modified": False,
           "9008_or_boot_validated": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name in PARTITION_SIZES:
        parser.add_argument(f"--{name.removesuffix('.img').replace('_', '-')}",
                            dest=name.removesuffix(".img").replace("-", "_"),
                            type=Path, required=True)
    args = parser.parse_args()
    replacements = {name: getattr(args, name.removesuffix(".img").replace("_", "_"))
                    for name in PARTITION_SIZES}
    assemble(args.base, args.output, replacements)


if __name__ == "__main__":
    main()
