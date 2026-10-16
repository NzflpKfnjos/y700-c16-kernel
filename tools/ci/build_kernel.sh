#!/usr/bin/env bash
# Build the hardware-specific component set. This script does not flash a device.
set -euo pipefail

workspace=""
metadata_dir=""
phase=all
usage() { printf 'Usage: %s --workspace PATH --metadata-dir PATH [--phase query|build|all]\n' "$0"; }
while (($#)); do
  case "$1" in
    --workspace|--metadata-dir|--phase)
      if (($# < 2)) || [[ -z "$2" || "$2" == --* ]]; then
        printf 'Missing value for %s\n' "$1" >&2; exit 2
      fi
      case "$1" in
        --workspace) workspace="$2" ;;
        --metadata-dir) metadata_dir="$2" ;;
        --phase) phase="$2" ;;
      esac
      shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ -z "$workspace" || -z "$metadata_dir" ]]; then
  usage >&2
  exit 2
fi
case "$phase" in query|build|all) ;; *) printf 'Invalid phase: %s\n' "$phase" >&2; exit 2 ;; esac
build_jobs="${BUILD_JOBS:-2}"
if [[ ! "$build_jobs" =~ ^[1-9][0-9]*$ ]]; then
  printf 'BUILD_JOBS must be a positive integer.\n' >&2
  exit 2
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
  printf 'This pinned toolchain requires an x86_64 Linux runner.\n' >&2
  exit 2
fi
workspace="$(realpath "$workspace")"
mkdir -p "$metadata_dir"
metadata_dir="$(realpath "$metadata_dir")"
target='//vendor/lenovo/sm8750:sun_perf_dist'
dist="$workspace/out/elden/dist"
if [[ ! -f "$metadata_dir/workspace-preparation.json" ]]; then
  printf 'Run prepare_workspace.py before building.\n' >&2
  exit 2
fi
cd "$workspace"
if [[ "$phase" != query && -d "$dist" && -n "$(find "$dist" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  printf 'Dist is not empty; use a fresh workspace to avoid mixing build outputs.\n' >&2
  exit 2
fi
mkdir -p "$dist"
printf 'Target: %s\nPhase: %s\nPage size: 4 KiB\nBazel/Kbuild jobs: %s\nDist: %s\n' \
  "$target" "$phase" "$build_jobs" "$dist" | tee "$metadata_dir/build-command-$phase.txt"

heartbeat_pid=""
active_phase=setup
timestamp() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
stop_heartbeat() {
  if [[ -n "$heartbeat_pid" ]]; then
    kill "$heartbeat_pid" 2>/dev/null || true
    wait "$heartbeat_pid" 2>/dev/null || true
    heartbeat_pid=""
  fi
}
heartbeat() {
  sleep_pid=""
  trap 'if [[ -n "$sleep_pid" ]]; then kill "$sleep_pid" 2>/dev/null || true; wait "$sleep_pid" 2>/dev/null || true; fi; exit 0' TERM INT
  while :; do
    {
      printf '\n[%s] %s resource snapshot\n' "$(timestamp)" "$active_phase"
      ps -eo pid,ppid,%cpu,%mem,rss,etime,comm --sort=-rss | head -n 13 || true
      free -h
      df -h "$workspace"
    } >> "$metadata_dir/$active_phase-heartbeat.log" 2>&1
    printf '[%s] %s running; resources in %s-heartbeat.log\n' "$(timestamp)" "$active_phase" "$active_phase"
    sleep 60 & sleep_pid=$!
    wait "$sleep_pid" || break
    sleep_pid=""
  done
}
collect_bazel_logs() {
  local source_root="$workspace/out/bazel/output_user_root" base log relative count=0
  [[ -d "$source_root" ]] || return 0
  mkdir -p "$metadata_dir/bazel-logs"
  while IFS= read -r -d '' base; do
    for log in "$base/command.log" "$base/server/jvm.out"; do
      [[ -f "$log" ]] || continue
      relative="${log#"$source_root/"}"
      # Keep the last MiB of at most eight known logs, never walk caches.
      tail -c 1048576 "$log" > "$metadata_dir/bazel-logs/$active_phase-${relative//\//_}" || true
      count=$((count + 1)); ((count < 8)) || return 0
    done
  done < <(find "$source_root" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
}
finish() {
  local status=$1
  trap - EXIT INT TERM
  stop_heartbeat
  collect_bazel_logs || true
  printf '[%s] Script exit=%s; last phase=%s\n' "$(timestamp)" "$status" "$active_phase" \
    | tee -a "$metadata_dir/phase-status.log" || true
  exit "$status"
}
trap 'finish $?' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_phase() {
  active_phase=$1
  local phase_log=$2 status
  shift 2
  printf '[%s] Begin %s\n' "$(timestamp)" "$active_phase" | tee -a "$metadata_dir/phase-status.log"
  heartbeat & heartbeat_pid=$!
  if /usr/bin/time -v -o "$metadata_dir/$active_phase-resources.txt" \
      "$@" 2>&1 | tee "$metadata_dir/$phase_log"; then
    status=0
  else
    status=$?
  fi
  stop_heartbeat
  collect_bazel_logs || true
  printf '[%s] End %s exit=%s\n' "$(timestamp)" "$active_phase" "$status" \
    | tee -a "$metadata_dir/phase-status.log"
  return "$status"
}

# The pinned manifest deliberately omits the standalone GBL build. Disable
# legacy WORKSPACE evaluation for query and build, as the author's wrapper does.
if [[ "$phase" == query || "$phase" == all ]]; then
  run_phase query target-query.log tools/bazel query --noenable_workspace "$target"
fi
if [[ "$phase" == build || "$phase" == all ]]; then
  run_phase build kernel-build.log tools/bazel run --noenable_workspace \
    --incompatible_sandbox_hermetic_tmp=false \
    --//build/kernel/kleaf:page_size=4k \
    --jobs="$build_jobs" --make_jobs="$build_jobs" \
    "$target" -- --destdir="$dist"
  printf 'Component build completed; image integration and device validation remain.\n'
fi
