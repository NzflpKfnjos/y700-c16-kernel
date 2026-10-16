#!/usr/bin/env python3
"""Check the kernel and modules from a sun/elden CI build; never flash images."""

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import traceback

from verify_device_trees import inspect_device_trees


def module_info(data):
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected ELF64 little-endian module")
    machine = struct.unpack_from("<H", data, 18)[0]
    section_offset = struct.unpack_from("<Q", data, 40)[0]
    entry_size, count, names_index = struct.unpack_from("<HHH", data, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, section_offset + i * entry_size)
                for i in range(count)]
    ns = sections[names_index]
    names = data[ns[4]:ns[4] + ns[5]]
    fields, versions = {}, False
    for section in sections:
        name = names[section[0]:names.index(b"\0", section[0])]
        if name == b".modinfo":
            for field in data[section[4]:section[4] + section[5]].split(b"\0"):
                if b"=" in field:
                    key, value = field.split(b"=", 1)
                    fields.setdefault(key.decode(errors="replace"), []).append(
                        value.decode(errors="replace"))
        versions |= name in (b"__versions", b"__version_ext_names")
    return {"machine": machine, "vermagic": fields.get("vermagic", []),
            "name": fields.get("name", []), "depends": fields.get("depends", []),
            "symbol_versions": versions}


def decompress_image(path):
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if data[:4] in (b"\x02\x21\x4c\x18", b"\x04\x22\x4d\x18"):
        return subprocess.run(["lz4", "-d", "-c", str(path)], check=True,
                              stdout=subprocess.PIPE).stdout
    return data


def module_payload(data, name):
    if name.endswith(".gz"):
        return gzip.decompress(data)
    if name.endswith(".xz"):
        import lzma
        return lzma.decompress(data)
    if name.endswith(".zst"):
        return subprocess.run(["zstd", "-d", "-c"], input=data,
                              stdout=subprocess.PIPE, check=True).stdout
    return data


def inspect(dist):
    errors, modules, kernels, inventory = [], [], [], []
    config = None

    def add_module(source, data):
        try:
            payload = module_payload(data, source)
            info = module_info(payload)
            modules.append({"source": source, "sha256": hashlib.sha256(payload).hexdigest(), **info})
            if info["machine"] != 183:
                errors.append(f"Module is not AArch64: {source}")
            if not info["symbol_versions"]:
                errors.append(f"Module has no symbol version section: {source}")
            if not info["vermagic"] or not all(x.startswith("6.12.") for x in info["vermagic"]):
                errors.append(f"Module does not identify as 6.12.x: {source}")
        except (ValueError, IndexError, struct.error) as exc:
            errors.append(f"Invalid module {source}: {exc}")

    for path in sorted(dist.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(dist))
        with path.open("rb") as source_file:
            digest = hashlib.file_digest(source_file, "sha256").hexdigest()
        inventory.append({"path": relative, "size": path.stat().st_size, "sha256": digest})
        if path.name in ("Image", "Image.gz", "Image.lz4"):
            image = decompress_image(path)
            banners = sorted(set(x.decode(errors="replace") for x in re.findall(
                rb"Linux version [\x20-\x7e]{1,400}", image)))
            arm64 = image[56:60] == b"ARM\x64"
            page_flag = ((struct.unpack_from("<Q", image, 24)[0] >> 1) & 3) if arm64 else None
            kernels.append({"path": relative, "banners": banners, "arm64_image": arm64,
                            "page_size_flag": page_flag})
            if not arm64 or not banners or not all(x.startswith("Linux version 6.12.") for x in banners):
                errors.append(f"Image is not an identifiable ARM64 6.12.x kernel: {relative}")
            if page_flag != 1:
                errors.append(f"Image does not declare 4 KiB pages: {relative}, flag={page_flag}")
            start = image.find(b"IKCFG_ST")
            if start >= 0:
                end = image.index(b"IKCFG_ED", start)
                config = gzip.decompress(image[start + 8:end]).decode()
        elif re.search(r"\.ko(?:\.(?:gz|xz|zst))?$", path.name):
            add_module(relative, path.read_bytes())
        elif path.name.endswith((".tar.gz", ".tgz", ".tar", ".tar.xz")):
            # Inspect in memory, never extract archive-controlled paths.
            with tarfile.open(path, "r:*") as archive:
                for member in archive:
                    if member.isfile() and re.search(r"\.ko(?:\.(?:gz|xz|zst))?$", member.name):
                        if member.size > 128 * 1024 * 1024:
                            errors.append(f"Oversized module member: {relative}:{member.name}")
                            continue
                        with archive.extractfile(member) as entry:
                            add_module(relative + ":" + member.name, entry.read())
        if path.name in (".config", "kernel.config") and config is None:
            config = path.read_text()

    if not kernels:
        errors.append("No Image, Image.gz or Image.lz4 in dist")
    if not modules:
        errors.append("No kernel modules found in dist or staging archives")
    kernel_versions = {match.group(1) for kernel in kernels for banner in kernel["banners"]
                       if (match := re.match(r"Linux version (\d+\.\d+\.\d+)", banner))}
    if len(kernel_versions) != 1:
        errors.append("Expected exactly one kernel patch version in dist")
    elif modules:
        expected = next(iter(kernel_versions))
        for module in modules:
            for vermagic in module["vermagic"]:
                version = re.match(r"(\d+\.\d+\.\d+)(?:[-+ ]|$)", vermagic)
                if not version or version.group(1) != expected:
                    errors.append(f"Module patch version differs from Image {expected}: {module['source']}")
    device_trees = inspect_device_trees(dist)
    errors.extend(device_trees["errors"])
    if not config:
        errors.append("No embedded IKCONFIG or exported kernel .config found")
    else:
        for option in ("CONFIG_ARM64_4K_PAGES=y", "CONFIG_MODULES=y", "CONFIG_MODVERSIONS=y"):
            if option not in config.splitlines():
                errors.append(f"Required kernel configuration missing: {option}")
    names = {n for module in modules for n in module["name"]}
    missing = sorted({"msm_drm", "msm_kgsl", "nvt_36xxx", "ufs_qcom", "lenovo_thermal_control"} - names)
    if missing:
        errors.append("Expected elden driver modules absent: " + ", ".join(missing))
    return {"status": "component_checks_passed" if not errors else "component_checks_failed",
            "boot_tested": False, "flashable_rom_package": False,
            "elden_overlay_runtime_selection_verified": False,
            "kernel_patch_versions": sorted(kernel_versions),
            "device_trees": device_trees,
            "limitations": "Static checks only; existing ROM integration, full symbol/UAPI validation and hardware testing remain required.",
            "errors": sorted(set(errors)), "kernels": kernels,
            "module_entries": len(modules), "unique_module_names": len(names),
            "vermagic_counts": dict(collections.Counter(x for m in modules for x in m["vermagic"])),
            "modules": modules, "inventory": inventory}, config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=Path(__file__).resolve().parents[2] / "ci/rom-baseline.json")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        report, config = inspect(args.dist)
    except (OSError, ValueError, IndexError, struct.error, EOFError,
            subprocess.SubprocessError, tarfile.TarError) as exc:
        (args.out / "verification-error.txt").write_text(traceback.format_exc())
        config = None
        report = {"status": "component_checks_failed", "boot_tested": False,
                  "flashable_rom_package": False,
                  "errors": [f"Artifact inspection did not complete: {exc}"],
                  "module_entries": 0, "unique_module_names": 0, "inventory": []}
    if args.baseline.is_file() and "modules" in report:
        baseline = json.loads(args.baseline.read_text())
        built_names = {n for module in report["modules"] for n in module["name"]}
        required = set(baseline["vendor_boot_module_names"])
        # Missing baseline names are integration leads, not automatic build
        # failures: this multi-platform ROM also carries inactive drivers.
        report["rom_baseline_comparison"] = {
            "baseline": baseline["source_package"],
            "baseline_module_count": len(required),
            "matched_count": len(required & built_names),
            "absent_module_names_for_review": sorted(required - built_names),
            "note": "Driver presence does not prove loaded state, ABI compatibility or equivalent replacement functionality."}
    (args.out / "component-checks.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.out / "SHA256SUMS").write_text("".join(f"{x['sha256']}  {x['path']}\n" for x in report["inventory"]))
    if config:
        (args.out / "kernel.config").write_text(config)
    summary = f"# elden 6.12 component checks\n\nStatus: {report['status']}\n\n"
    summary += f"Module entries: {report['module_entries']}; unique module names: {report['unique_module_names']}.\n\n"
    summary += "Boot testing and integration into the ColorOS port are still pending. This artifact is not a validated flash package.\n"
    for error in report["errors"]:
        summary += "\n- " + error
    (args.out / "component-checks.md").write_text(summary + "\n")
    print(summary)
    raise SystemExit(0 if not report["errors"] else 1)


if __name__ == "__main__":
    main()
