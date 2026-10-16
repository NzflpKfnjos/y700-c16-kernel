# Y700 Gen 4 elden 6.12 public build-input audit

Checked 2026-10-16 (Asia/Singapore). Scope: a small number of public HTML/raw files and Git remote refs. No source checkout, build, downloaded kernel release, or device operation was performed.

## Result

The `turbo-boo` repositories contain substantive work porting Lenovo elden drivers and DTs to a 6.12 Qualcomm/DDK build. They are credible development inputs, but the checked public pages do **not** establish a complete reproducible, tested 6.12 package for `c16-300-9008-V17.6`.

The apparent `VERSION=6 / PATCHLEVEL=11` in the SoC repository is **not enough to reject the 6.12 branch**: the actual Kleaf build takes its GKI kernel, Makefile, and most common source files from a separate workspace `common/` repository. The missing fact is the author's exact `common/` revision and matching build-tool manifest.

No author-provided exact manifest, standalone kernel build README, or downloadable release was found on the checked repository/profile pages. An upstream LineageOS 6.12 manifest was independently confirmed below, but its applicability to this author's elden branch is unconfirmed. The kernel Releases page explicitly says “There aren’t any releases here”. Its Actions page renders the generic Actions introduction, with no visible run listing. This is limited to that checked repository; it is not proof no external build or private CI exists.

## Public refs observed

- Kernel/SoC tree: https://github.com/turbo-boo/android_kernel_lenovo_sm8750/tree/elden-6.12 — HEAD `587fb3b9e6a7fea873241b8c41b911bb8af495fb`.
- Modules tree: https://github.com/turbo-boo/android_kernel_lenovo_sm8750-modules/tree/elden-6.12 — HEAD `2f72151adab1ed228b9c6557ae64fbabc4388d2d`.
- Device trees: https://github.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees/tree/elden-6.12 — HEAD `dd911f5c0b6c52417b44a8f7679785b0c284b412`.
- Release page checked: https://github.com/turbo-boo/android_kernel_lenovo_sm8750/releases
- Actions page checked: https://github.com/turbo-boo/android_kernel_lenovo_sm8750/actions
- Profile repositories checked: https://github.com/turbo-boo?tab=repositories and page 2. No matching common-kernel/manifest repository appeared in those lists.

## Evidence for a real 6.12 build design

1. `kleaf-scripts/android_build.bzl` writes `KERNEL_DIR=common`, loads `//common:modules.bzl`, and uses `//common:build.config.gki.aarch64`. `BUILD.bazel` sets the `msm_kernel_build` label default to `//common:kernel_aarch64`. The DT build explicitly uses `makefile = "//common:Makefile"` and `//common:kernel_aarch64_sources`.
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/kleaf-scripts/android_build.bzl
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/BUILD.bazel
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/kleaf-scripts/dtbs.bzl
2. `common_sources.bzl` explains that lightly modified or unmodified drivers are copied directly from ACK. The SoC repository therefore cannot be treated as a self-contained normal Linux tree.
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/common_sources.bzl
3. Recent commit list includes “Fix 6.12 build errors from the Lenovo ports”, “Rebase Lenovo Huaqin USB Ethernet stack onto ACK 6.12”, “Build the peach v1 WLAN driver for sun”, and an import from `LineageOS/android_kernel_qcom_sm8850 lineage-24.0`. These are source-development evidence, not evidence of successful boot or hardware validation. Most visible port work is dated 2026-10-15 and 2026-10-16.
   - https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commits/elden-6.12/
   - https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commit/0653e99b758ee57c05ca7c130284a20986f2816b
   - https://github.com/turbo-boo/android_kernel_lenovo_sm8750/commit/e830581a386cc73df24456e6ef73f275d0540018
4. `configs/sun_perf.bzl` enables Lenovo hyper scheduler, Lenovo thermal controls, Huaqin helpers, Novatek touch, and the relevant Qualcomm sun modules. `qcom/platform_map.bzl` includes the board-specific `sun-elden-overlay.dtbo` under sun, plus separate display/camera/audio/GPU techpack overlays.
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/configs/sun_perf.bzl
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750-devicetrees/elden-6.12/qcom/platform_map.bzl
5. `techpack_modules.bzl` includes camera, DSP, audio, display, graphics, video, Wi-Fi and other vendor kernel modules. Its sun exception says stock elden loads peach WLAN v1/v2, and excludes `msm_hfi_core` because stock elden has no such module. This is further evidence the work targets Lenovo's hardware rather than just renaming a generic GKI image.
   - https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/kleaf-scripts/techpack_modules.bzl

## Workspace layout and available build entry points

The source files explicitly expect these paths relative to a shared kernel workspace:

```text
common/                             actual ACK/GKI source, exact revision unlocated
build/kernel/                       matching Kleaf, exact revision unlocated
vendor/lenovo/sm8750/                kernel/SoC repo above
vendor/lenovo/sm8750-modules/        modules repo above
vendor/lenovo/sm8750-devicetrees/    DT repo above
prebuilts/...                       matching clang, Rust, build tools
tools/bazel                         launcher from Kleaf
tools/mkbootimg/                    boot image tooling
external/...                       Bazel dependencies; qcom-dtc is referenced
```

Path evidence:

- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/soc_repo_path.bzl
- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750-modules/elden-6.12/kleaf/repo_paths.bzl
- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/kleaf-scripts/msm_kernel_extensions.bzl
- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/bazel.WORKSPACE

The source declares target `sun` with `perf` and `consolidate` variants. Reading the rules implies a primary distribution label `//vendor/lenovo/sm8750:sun_perf_dist`. Therefore the following is a **candidate command derived from the rules, not an author-documented or executed successful build**:

```sh
tools/bazel run //vendor/lenovo/sm8750:sun_perf_dist
```

`build_with_bazel.py` accepts `-t TARGET VARIANT` and can perform `--dry-run`, but it still determines the workspace as the immediate parent of its own directory and contains old `../soc-repo/...` setup defaults. With the new nested `vendor/lenovo/sm8750` layout, it should not be presented as a known-good invocation without confirming how the maintainer installs/patches it.

- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/build_with_bazel.py
- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/kleaf-scripts/targets/sun.bzl
- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/target_variants.bzl

The rules are designed to produce kernel/GKI artifacts, modules, DTBO, vendor_boot, vendor_dlkm and system_dlkm images. This is a kernel component build, not a complete OnePlus-port ROM packager. The extension currently returns no prebuilt init_boot, no vendor ramdisk binaries, and no extra board packaging. Generic boot AVB signing also uses a test key and a fixed OS-version property. Those outputs require integration with the existing ROM's header/cmdline/ramdisk/AVB and module-load layout before they can be considered suitable flash images.

## Public AOSP 6.12 manifest: reference only

An additional upstream manifest was identified by the parallel researcher and independently read for this audit:

https://github.com/LineageOS/android/blob/lineage-24.0/snippets/kernel-6.12.xml

It maps `kernel/platform/kernel-6.12/common` to AOSP `kernel/common` revision `android16-6.12-2026-06`, and `build/kernel` plus most tool projects to `main-kernel-2025`. This matters because elden's SoC branch recently imported LineageOS `android_kernel_qcom_sm8850` `lineage-24.0` changes. It is a plausible upstream starting point, **not a frozen elden manifest**: most entries use moving branch revisions, and there is no verified source claim that turbo-boo used this exact common branch. The common Makefile at that branch currently reports 6.12.81.

- https://raw.githubusercontent.com/LineageOS/android/lineage-24.0/snippets/kernel-6.12.xml
- https://android.googlesource.com/kernel/common/+/refs/heads/android16-6.12-2026-06/Makefile

An official, publicly readable manifest exists:

https://android.googlesource.com/kernel/manifest/+/refs/heads/common-android16-6.12/default.xml

It maps `common` to `kernel/common` revision `android16-6.12`, the `common-android16-6.12` superproject, and Kleaf/build-tool projects with default `main-kernel-2025`. Its documented repo-init form is derivable as:

```sh
repo init -u https://android.googlesource.com/kernel/manifest -b common-android16-6.12
```

This locates genuine Android 16/6.12 common source and tools. It does **not** identify turbo-boo's exact matching common/Kleaf commit, Qualcomm additions or local manifest. The SoC tree still lists `CLANG_VERSION=r536225` and `RUSTC_VERSION=1.81.0.u1`; the actual active toolchain is controlled by the common/Kleaf configuration and cannot be concluded from these SoC defaults alone.

- https://raw.githubusercontent.com/turbo-boo/android_kernel_lenovo_sm8750/elden-6.12/build.config.constants

## Relation to the present OnePlus port and vendor HALs

Replacing the current 6.6 `Image` with an arbitrary 6.12 GKI build will not make the current 6.6 vendor modules load on 6.12. All required Qualcomm/Lenovo kernel modules must be rebuilt against the selected 6.12 common kernel and symbol ABI, with matching DT/DTBO, load order and firmware interfaces. The public work appears intended to do that rebuild, but its compatibility with this particular ROM remains unverified.

The available repository files are kernel-side only. They do **not** prove that a different Android vendor HAL stack is strictly required, nor that the existing one is compatible. Existing HALs may remain usable if all exposed vendor UAPIs and firmware contracts are preserved; substantial upgrades of the Qualcomm camera/display/audio/GPU drivers can require matching HAL/blob/firmware versions. The exact requirement must be established by comparing the current ROM's vendor blobs/firmware and driver interfaces with this port, then by boot and hardware tests. A branch name or successfully compiled kernel is insufficient.

The public `android_device_lenovo_TB322FC` repository defaults to `twrp-16.0`; its README documents a TWRP recovery build. It is not a complete elden Android 16/6.12 ROM manifest, nor proof that this OnePlus ROM can use the new kernel.

- https://github.com/turbo-boo/android_device_lenovo_TB322FC
- https://raw.githubusercontent.com/turbo-boo/android_device_lenovo_TB322FC/twrp-16.0/README.md

## Inputs still needed to make a reviewable candidate

1. Maintainer's exact `common` and `build/kernel` source refs plus complete local manifest/tool dependencies, ideally a pinned `repo manifest -r`.
2. A known successful sun/elden 6.12 build log and its resulting kernel config, `kernelrelease`, Module.symvers/KMI metadata, and all required module/DT outputs.
3. Confirmation of the vendor/firmware baseline used to test that port and whether any HAL/blob changes were necessary.
4. The current ROM's boot-family headers, ramdisks and AVB metadata; vendor/system DLKM module metadata and load lists; compatible DT selection; partition format and size requirements.
5. A controlled boot and functional validation on the exact hardware/ROM combination before claiming the upgrade is complete.

No verified bootable 6.12 candidate was produced by this audit.
