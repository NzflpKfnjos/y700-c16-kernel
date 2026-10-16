# elden 6.12 GitHub Actions build graph review

Checked on 2026-10-16/17, Asia/Singapore. Source review and local glue fixtures only; no kernel was compiled in this review. Root task owns the actual GitHub Actions run.

## Build entry point

The frozen Lenovo SoC commit `587fb3b9e6a7fea873241b8c41b911bb8af495fb` declares `define_sun()`, which invokes `define_typical_android_build(name = "sun", ...)`. Its perf branch passes `base_kernel = ":msm_kernel_build"`; that label flag resolves to `//common:kernel_aarch64`. `define_single_android_build()` creates `sun_perf_dist` using `rules_pkg` `pkg_install`.

Run from the shared workspace root:

```sh
tools/bazel query --noenable_workspace //vendor/lenovo/sm8750:sun_perf_dist
tools/bazel run --noenable_workspace \
  --incompatible_sandbox_hermetic_tmp=false \
  --//build/kernel/kleaf:page_size=4k --jobs=2 \
  //vendor/lenovo/sm8750:sun_perf_dist \
  -- --destdir="$PWD/out/elden/dist"
```

`tools/ci/build_kernel.sh` implements those commands, logs query/build separately, enables pipefail, rejects non-Linux/non-x86_64 hosts and a nonempty dist, and allows `BUILD_JOBS` to override 2. It does not invoke ABL, flash anything, suppress kernel symbol checks, or turn compilation failures into success.

Avoid the inherited `build_with_bazel.py` for this workspace. It derives the workspace from the immediate parent of its own real path, so the nested Lenovo checkout resolves to `vendor/lenovo`, then searches there for `tools/bazel`. It also retains `../soc-repo` extensions and `//soc-repo:skip_*` paths. Its recent `--noenable_workspace` and fake-module overrides do not repair that path assumption.

## Why the initial AOSP-only build/kernel selection is inadequate

The initial research lock selected AOSP kernel/build `08bb5611333aa1731ad7400e3f6e8af6500a1151`. Direct source review confirmed that its `kleaf/BUILD.bazel` has no `socrepo` build setting and its DDK lacks Qualcomm's `ddk_library(pkvm_el2=...)` argument. Lenovo's `device.bazelrc` passes `socrepo=true`, and its library registry forwards `pkvm_el2` for hypervisor libraries. Dropping those arguments would conceal a missing build implementation.

A real public Qualcomm implementation was located and inspected through a small filtered/sparse checkout:

- Repository: <https://git.codelinaro.org/clo/la/kernel/build.git>
- Branch observed: `kernel.lnx.6.12.r69-rel`
- Frozen commit: `af73dd2482b6e6d4ea181f378a4b49fb7970655f`
- `kleaf/BUILD.bazel` defines `socrepo`, `socrepo_true`, `socrepo_false`.
- `kleaf/impl/ddk/ddk_library.bzl` implements `pkvm_el2`; `makefiles.bzl` passes and handles the corresponding `module_pkvm_el2`.
- The `common_kernel`, `kernel_build`, and `ddk_module` named arguments agree with the initial AOSP candidate in the inspected function signatures. This supports using the Qualcomm build implementation with the selected common baseline but does not prove the entire combined tree builds or boots.

The source-sync agent owns the updated frozen manifest and lock. This is a researched build combination, not the maintainer's recovered exact manifest.

## Workspace glue implemented

`tools/ci/prepare_workspace.py` checks common Makefile version 6.12, rejects explicit 16K/64K common defconfigs, verifies Qualcomm socrepo/pkvm implementation, and then writes:

1. Root `MODULE.bazel` as a copy of Qualcomm's `kleaf/bzlmod/bazel.MODULE.bazel`, changing its old `soc-repo/BUILD.dtc` declaration to generated `ci-glue/BUILD.dtc`. The pinned repository's MODULE source is preserved.
2. Root `device.bazelrc` copied from Lenovo's file, replacing the old `//soc-repo:unsafe_headers_qcom_group` package with the actual nested Lenovo package. Kleaf's `common.bazelrc` automatically imports root `device.bazelrc`.
3. `build/qcom_build_extensions` symlink to the SoC's genuine extension package, which defines the `qtisocrepo` string setting used in `device.bazelrc`.
4. `build/msm_kernel_extensions.bzl` symlink to the SoC extension file for inherited consumers.
5. DTC's `external/qcom-dtc/version_gen.h`, generated from its Makefile version fields. The pinned Lineage DTC commit `c1197f56b8f468effbbf5e79feae353c4280e2ea` reports 1.7.0 and `util.c` includes `version_gen.h`; Lenovo's inherited `BUILD.dtc` instead declares nonexistent `version_non_gen.h` in auxiliary binary srcs. Generated `ci-glue/BUILD.dtc` corrects those declarations to `version_gen.h`; this changes no DTC functionality. The source repo's BUILD.dtc is preserved.

Each generated text file has a SHA-256 record, and the setup uploads a unified diff as `workspace-glue.patch`. Symlink targets are recorded. A local fixture verified successful setup, idempotent rerun, preservation of the original MODULE, correct DTC version generation, and rejection of a wrong common LTS.

Qualcomm's MODULE already registers `@dtc` as a Bzlmod local repository, so merely concatenating Lenovo's `bazel.WORKSPACE` is unnecessary and ineffective with legacy WORKSPACE disabled. Qualcomm also registers `external/bazel-contrib-rules_devicetree`; the sync agent found and froze its public AOSP `main-kernel` commit `bc0509e0ae6195f9a47764c3d846459f713fa741`.

Both query and build pass `--noenable_workspace`: the reduced manifest deliberately does not include the unrelated standalone GBL toolchain that legacy `WORKSPACE.bzlmod` would attempt to load. The Kleaf launcher itself supplies fake-module overrides, so copying the old wrapper's three hardcoded overrides is unnecessary.

## Dependency and output relationships

The SoC registry produces the perf DDK configuration and per-module targets against `//common:kernel_aarch64`, including the base common headers and SoC headers. The libraries registry supplies the declared DDK library graph; the module registry supplies intra-SoC module deps, hooks, and library deps. `define_techpack_modules()` adds the modules repository's camera, GPU, display, DSP, audio, video, touch, networking, securemsm, and WLAN targets to the distribution.

The distribution is broader than `Image`: `android_build.bzl` requests GKI artifacts, rebuilt modules, DTBs and DTBOs, `vendor_boot.img`, `vendor_dlkm.img`, GKI `system_dlkm` images in ext4/erofs and flattened forms, merged UAPI/header archives, module load/block lists, and a synthetic DLKM-only super image. `init_boot` export and vendor ramdisk extension functions return no additions; a complete stock/port ramdisk is not supplied by this branch.

The synthetic `super.img` is defined with `super_img_size = 0x22000000`, containing just `system_dlkm` and `vendor_dlkm`. It must never replace the existing ROM's full dynamic-partition super image. Generic boot signing uses a checked-in test key and fixed Android 13 / 2023-05-05 properties. Neither that boot image, the vendor_boot, nor any DLKM/DT image is established as flash-compatible with the current OnePlus-port ROM merely because the build succeeds.

## Artifact verification requirements

- Verify actual Image ARM64 header, version banner 6.12.x, and ARM64 header page-size bits indicating 4 KiB; check `.config`/IKCONFIG for `CONFIG_ARM64_4K_PAGES=y`, no 16K/64K, and module versioning. `PAGE_SIZE=4096` inside a boot-image config alone is not kernel page-size proof.
- Inspect every unpacked or archived `.ko` for AArch64 ELF, matching 6.12 vermagic and symbol-version sections. Compare required stock module basenames and dependency/load metadata with the new artifact set; flattening can hide collisions.
- Preserve the resolved manifest, all input HEADs, workspace-glue diff/hashes, stdout/stderr, final configs, Module.symvers and checksums.
- Check that the board-specific `sun-elden-overlay.dtbo` exists alongside the required base/techpack DT outputs. Confirm actual board IDs and selection during later ROM integration.
- A successful component build cannot establish ROM boot-header/cmdline/ramdisk/AVB compatibility, HAL/firmware compatibility, functional hardware, or a successful device boot. Mark artifacts as unvalidated components pending those steps.

Root's `tools/ci/verify_dist.py` owns the automated dist audit. Any compile, modpost, missing-source, DT, or packaging error from the real runner should be treated as new evidence and fixed explicitly; this review does not predeclare the branch error-free.
