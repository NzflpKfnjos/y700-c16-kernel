#!/usr/bin/env python3
"""Replace only the kernel in a stock boot v4 image and emit an unsigned candidate."""

import argparse
import hashlib
from pathlib import Path
import re
import struct


PAGE_SIZE = 4096
PARTITION_SIZE = 100663296


def make_candidate(stock_boot: Path, kernel_image: Path, output: Path):
    stock_boot = stock_boot.resolve()
    kernel_image = kernel_image.resolve()
    output = output.resolve()
    if output in (stock_boot, kernel_image):
        raise ValueError("Output must be different from both inputs")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")

    original = stock_boot.read_bytes()
    kernel = kernel_image.read_bytes()
    if original[:8] != b"ANDROID!":
        raise ValueError("Stock image is not an Android boot image")
    version = struct.unpack_from("<I", original, 40)[0]
    header_size = struct.unpack_from("<I", original, 20)[0]
    kernel_size, ramdisk_size = struct.unpack_from("<II", original, 8)
    if version != 4 or header_size != 1584 or len(original) != PARTITION_SIZE:
        raise ValueError("Expected stock boot v4 image for a 96 MiB partition")
    if ramdisk_size != 0:
        raise ValueError("Refusing to replace a boot image with a nonempty ramdisk")
    if struct.unpack_from("<I", original, 1580)[0] != 0:
        raise ValueError("Refusing to discard a nonempty boot v4 signature")
    if len(kernel) < 64 or kernel[56:60] != b"ARM\x64":
        raise ValueError("Kernel input is not an ARM64 Image")
    banners = re.findall(rb"Linux version ([\x20-\x7e]{1,300})", kernel)
    if not banners or not all(x.startswith(b"6.12.") for x in banners):
        raise ValueError("Kernel input does not identify as Linux 6.12.x")
    if PAGE_SIZE + len(kernel) > PARTITION_SIZE:
        raise ValueError(f"Kernel does not fit the {PARTITION_SIZE}-byte boot partition")

    header = bytearray(original[:PAGE_SIZE])
    struct.pack_into("<I", header, 8, len(kernel))
    image = bytes(header) + kernel
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        destination.write(image)
    print({"output": str(output), "sha256": hashlib.sha256(image).hexdigest(),
           "kernel_size": len(kernel), "kernel_version": banners[0].decode(),
           "stock_header_preserved_except_kernel_size": True,
           "stock_ramdisk_size": ramdisk_size, "partition_size": PARTITION_SIZE,
           "requires_avb_footer": True, "candidate_only": True,
           "flashable_or_boot_validated": False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-boot", type=Path, required=True)
    parser.add_argument("--kernel-image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    make_candidate(args.stock_boot, args.kernel_image, args.output)


if __name__ == "__main__":
    main()
