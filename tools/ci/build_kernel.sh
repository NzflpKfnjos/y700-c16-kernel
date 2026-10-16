#!/usr/bin/env bash
# Build the hardware-specific component set. This script does not flash a device.
set -euo pipefail

workspace=""
metadata_dir=""
while (($#)); do
  case "$1" in
    --workspace) workspace="$2"; shift 2 ;;
    --metadata-dir) metadata_dir="$2"; shift 2 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ -z "$workspace" || -z "$metadata_dir" ]]; then
  printf 'Usage: %s --workspace PATH --metadata-dir PATH\n' "$0" >&2
  exit 2
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  printf 'This pinned toolchain requires an x86_64 Linux runner.\n' >&2
  exit 2
fi
workspace="$(realpath "$workspace")"
mkdir -p "$metadata_dir"
metadata_dir="$(realpath "$metadata_dir")"
build_jobs="${BUILD_JOBS:-2}"
if [[ ! "$build_jobs" =~ ^[1-9][0-9]*$ ]]; then
  printf 'BUILD_JOBS must be a positive integer.\n' >&2
  exit 2
fi
target='//vendor/lenovo/sm8750:sun_perf_dist'
dist="$workspace/out/elden/dist"
if [[ ! -f "$metadata_dir/workspace-preparation.json" ]]; then
  printf 'Run prepare_workspace.py before building.\n' >&2
  exit 2
fi
cd "$workspace"
if [[ -d "$dist" && -n "$(find "$dist" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  printf 'Dist is not empty; use a fresh workspace to avoid mixing build outputs.\n' >&2
  exit 2
fi
mkdir -p "$dist"
printf 'Target: %s\nPage size: 4 KiB\nParallel jobs: %s\nDist: %s\n' \
  "$target" "$build_jobs" "$dist" | tee "$metadata_dir/build-command.txt"

# The pinned manifest deliberately omits the standalone GBL build. Disable
# legacy WORKSPACE evaluation for query and build, as the author's wrapper does.
tools/bazel query --noenable_workspace "$target" \
  2>&1 | tee "$metadata_dir/target-query.log"
tools/bazel run --noenable_workspace \
  --incompatible_sandbox_hermetic_tmp=false \
  --//build/kernel/kleaf:page_size=4k \
  --jobs="$build_jobs" \
  "$target" -- --destdir="$dist" \
  2>&1 | tee "$metadata_dir/kernel-build.log"
printf 'Component build completed; image integration and device validation remain.\n'
