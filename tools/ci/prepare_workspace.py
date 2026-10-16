#!/usr/bin/env python3
"""Prepare the pinned Qualcomm Kleaf workspace without changing kernel code."""

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re


SOC = "vendor/lenovo/sm8750"


def make_values(path):
    return dict(re.findall(r"^(VERSION|PATCHLEVEL|SUBLEVEL|EXTRAVERSION)[ \t]*=[ \t]*(.*?)[ \t]*$",
                           path.read_text(), re.M))


def prepare(workspace, metadata):
    workspace = workspace.resolve()
    metadata.mkdir(parents=True, exist_ok=True)
    source = workspace / SOC
    required = ["common/Makefile", "common/arch/arm64/configs/gki_defconfig",
                "build/kernel/kleaf/bzlmod/bazel.MODULE.bazel",
                "build/kernel/kleaf/impl/ddk/ddk_library.bzl", "tools/bazel",
                f"{SOC}/BUILD.bazel", f"{SOC}/BUILD.dtc", f"{SOC}/device.bazelrc",
                "vendor/lenovo/sm8750-modules/kleaf/repo_paths.bzl",
                "vendor/lenovo/sm8750-devicetrees/qcom/platform_map.bzl",
                "external/qcom-dtc/Makefile", "external/qcom-dtc/fdtoverlaymerge.c",
                "external/bazel-contrib-rules_devicetree/MODULE.bazel"]
    missing = [path for path in required if not (workspace / path).is_file()]
    if missing:
        raise ValueError("Missing build inputs: " + ", ".join(missing))
    version = make_values(workspace / "common/Makefile")
    if (version.get("VERSION"), version.get("PATCHLEVEL")) != ("6", "12"):
        raise ValueError(f"Expected common Linux 6.12, found {version}")
    defconfig = (workspace / "common/arch/arm64/configs/gki_defconfig").read_text()
    if re.search(r"^CONFIG_ARM64_(16K|64K)_PAGES=y$", defconfig, re.M):
        raise ValueError("The common defconfig enables a page size other than 4 KiB")
    kleaf_build = (workspace / "build/kernel/kleaf/BUILD.bazel").read_text()
    if 'name = "socrepo"' not in kleaf_build:
        raise ValueError("Expected the pinned Qualcomm Kleaf with its socrepo flag")
    if "pkvm_el2 =" not in (workspace / "build/kernel/kleaf/impl/ddk/ddk_library.bzl").read_text():
        raise ValueError("Qualcomm DDK pkvm_el2 support is missing")

    changes, patches = [], []

    def write(relative, text, original="", reason=""):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Manifest linkfiles are symlinks. Keep the pinned repository untouched.
        if target.is_symlink():
            target.unlink()
        target.write_text(text)
        changes.append({"path": relative, "reason": reason,
                        "sha256": hashlib.sha256(text.encode()).hexdigest()})
        patches.extend(difflib.unified_diff(original.splitlines(keepends=True),
                                          text.splitlines(keepends=True),
                                          fromfile=relative + ".upstream", tofile=relative))

    def link(relative, destination):
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise ValueError(f"Refusing to replace existing non-symlink: {target}")
        target.symlink_to(os.path.relpath(workspace / destination, target.parent),
                          target_is_directory=(workspace / destination).is_dir())
        changes.append({"path": relative, "symlink": os.readlink(target)})

    module_source = workspace / "build/kernel/kleaf/bzlmod/bazel.MODULE.bazel"
    module = module_source.read_text()
    old = 'build_file = "soc-repo/BUILD.dtc"'
    if module.count(old) != 1:
        raise ValueError("Unexpected Qualcomm MODULE.bazel dtc registration")
    # The DTC source includes version_gen.h; the inherited Qualcomm BUILD file
    # names version_non_gen.h. Use the actual source include and generate its
    # version using the source Makefile, as DTC's normal make build does.
    dtc_build = (source / "BUILD.dtc").read_text()
    if '"version_non_gen.h"' not in dtc_build:
        raise ValueError("Unexpected Qualcomm BUILD.dtc version header entries")
    write("ci-glue/BUILD.dtc", dtc_build.replace('"version_non_gen.h"', '"version_gen.h"'),
          dtc_build, "Declare the version header included by the pinned DTC source")
    module = module.replace(old, 'build_file = "ci-glue/BUILD.dtc"')
    write("MODULE.bazel", module, module_source.read_text(),
          "Use the nested Lenovo layout and adapted DTC build declaration")

    device_rc = (source / "device.bazelrc").read_text()
    if "//soc-repo:unsafe_headers_qcom_group" not in device_rc:
        raise ValueError("Unexpected device.bazelrc unsafe-header label")
    write("device.bazelrc", device_rc.replace("//soc-repo:", f"//{SOC}:"),
          device_rc, "Resolve the real Lenovo package without a duplicate soc-repo alias")
    link("build/qcom_build_extensions", f"{SOC}/qcom_build_extensions")
    link("build/msm_kernel_extensions.bzl", f"{SOC}/kleaf-scripts/msm_kernel_extensions.bzl")

    dtc_version = make_values(workspace / "external/qcom-dtc/Makefile")
    if any(not dtc_version.get(key, "").isdigit() for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL")):
        raise ValueError("Cannot determine DTC version from its Makefile")
    dtc_release = ".".join(dtc_version[key] for key in ("VERSION", "PATCHLEVEL", "SUBLEVEL"))
    dtc_release += dtc_version.get("EXTRAVERSION", "")
    header = f'#define DTC_VERSION "DTC {dtc_release}"\n'
    write("external/qcom-dtc/version_gen.h", header,
          reason="Generate DTC's normal version header from the pinned source Makefile")

    result = {"status": "workspace_prepared_not_built", "common_version": version,
              "target": f"//{SOC}:sun_perf_dist", "page_size": "4k",
              "changes": changes,
              "note": "Only workspace wiring and DTC version-header declarations were changed. "
                      "Kernel ABI, symbols and compilation checks remain enabled."}
    (metadata / "workspace-preparation.json").write_text(json.dumps(result, indent=2) + "\n")
    (metadata / "workspace-glue.patch").write_text("".join(patches))
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--metadata-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.workspace, args.metadata_dir)


if __name__ == "__main__":
    main()
