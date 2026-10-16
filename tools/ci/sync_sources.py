#!/usr/bin/env python3
"""Sync the frozen elden 6.12 Linux build inputs, without touching ROM images.

The checked-in manifest contains commit IDs only.  --plan validates that lock
without network access.  Actual sync needs Linux x86_64, Python 3, git and curl.
Source compatibility/setup is a separate step; syncing is not a build result.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = PROJECT_ROOT / "ci/source-lock.json"
MARKER = ".y700-kernel-workspace.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")


def run(args: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    print("+ " + shlex.join(args), flush=True)
    result = subprocess.run(
        args, cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else ""


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def safe_relative(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Unsafe manifest path: {value!r}")


def load_inputs() -> tuple[dict, Path, list[ET.Element]]:
    lock = json.loads(LOCK_PATH.read_text())
    safe_relative(lock["manifest"])
    manifest = PROJECT_ROOT / lock["manifest"]
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if digest != lock["manifest_sha256"]:
        raise ValueError("Manifest SHA256 differs from ci/source-lock.json")
    root = ET.parse(manifest).getroot()
    if root.findall("include") or root.findall("superproject"):
        raise ValueError("Expected a standalone, fully frozen manifest")
    expected = {item["path"]: item for item in lock["projects"]}
    projects = root.findall("project")
    seen: set[str] = set()
    for project in projects:
        path = project.attrib["path"]
        safe_relative(path)
        if path in seen:
            raise ValueError(f"Duplicate project path: {path}")
        seen.add(path)
        revision = project.attrib.get("revision", "")
        if not SHA.fullmatch(revision) or expected.get(path, {}).get("revision") != revision:
            raise ValueError(f"Missing/mismatched pinned revision: {path}")
        for link in project:
            if link.tag not in ("linkfile", "copyfile"):
                raise ValueError(f"Unsupported manifest element: {link.tag}")
            safe_relative(link.attrib["src"])
            safe_relative(link.attrib["dest"])
    if seen != set(expected):
        raise ValueError("Manifest and source-lock project paths differ")
    return lock, manifest, projects


def record_versions(metadata: Path) -> None:
    result = {
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git": run(["git", "--version"], capture=True).strip(),
        "curl": run(["curl", "--version"], capture=True).splitlines()[0],
    }
    write_json(metadata / "sync-host.json", result)


def install_repo(lock: dict, metadata: Path) -> Path:
    repo_tool = lock["repo_tool"]
    revision = repo_tool["commit"]
    if not SHA.fullmatch(revision):
        raise ValueError("repo launcher must be pinned to a commit")
    encoded = run([
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "3", "--connect-timeout", "30", "--max-time", "180",
        f"{repo_tool['url']}/+/{revision}/repo?format=TEXT",
    ], capture=True)
    launcher = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(launcher).hexdigest() != repo_tool["launcher_sha256"]:
        raise ValueError("Downloaded repo launcher SHA256 does not match source lock")
    tool_dir = metadata / "tools"
    tool_dir.mkdir(exist_ok=True)
    path = tool_dir / "repo"
    path.write_bytes(launcher)
    path.chmod(0o755)
    return path


def init_manifest_repository(manifest: Path, metadata: Path) -> Path:
    # A local manifest repository keeps every build input pinned and avoids a
    # dependency on this CI repository already having a GitHub remote.
    target = metadata / "manifest-repository"
    target.mkdir(exist_ok=True)
    if not (target / ".git").exists():
        run(["git", "init", "--initial-branch=main", str(target)])
    copied = target / "default.xml"
    copied.write_bytes(manifest.read_bytes())
    run(["git", "add", "default.xml"], cwd=target)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=target, check=False,
    ).returncode
    if changed == 1:
        run([
            "git", "-c", "user.name=Y700 Kernel CI", "-c",
            "user.email=y700-kernel-ci@users.noreply.github.com", "commit",
            "--no-gpg-sign", "-m", "Freeze elden 6.12 build inputs",
        ], cwd=target)
    elif changed != 0:
        raise RuntimeError("Cannot inspect local manifest repository")
    return target


def verify_checkout(workspace: Path, projects: list[ET.Element], metadata: Path) -> None:
    observed = []
    for project in projects:
        path = workspace / project.attrib["path"]
        actual = run(["git", "rev-parse", "HEAD"], cwd=path, capture=True).strip()
        wanted = project.attrib["revision"]
        observed.append({"path": project.attrib["path"], "expected": wanted, "actual": actual})
        if actual != wanted:
            write_json(metadata / "checkout-verification.json", observed)
            raise RuntimeError(f"Checkout revision mismatch: {path}")
        for link in project:
            src = path / link.attrib["src"]
            dest = workspace / link.attrib["dest"]
            if not src.exists() or not dest.exists():
                raise RuntimeError(f"Missing manifest {link.tag}: {src} -> {dest}")
            if link.tag == "linkfile" and (
                not dest.is_symlink() or src.resolve() != dest.resolve()
            ):
                raise RuntimeError(f"Unexpected manifest symlink target: {dest}")
            if link.tag == "copyfile" and src.read_bytes() != dest.read_bytes():
                raise RuntimeError(f"Unexpected manifest copy: {dest}")
    write_json(metadata / "checkout-verification.json", observed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="Empty/new Linux kernel workspace")
    parser.add_argument("--metadata-dir", type=Path, required=True, help="Build records, outside source workspace")
    parser.add_argument("--jobs", type=int, default=8, help="Parallel repo fetches (default: 8)")
    parser.add_argument("--min-free-gib", type=float, default=45, help="Minimum available space before sync (default: 45 GiB)")
    parser.add_argument("--plan", action="store_true", help="Validate lock and print plan; no network or source sync")
    args = parser.parse_args()
    if args.jobs < 1 or args.min_free_gib < 0:
        parser.error("--jobs must be positive; --min-free-gib must be nonnegative")
    workspace = args.workspace.expanduser().resolve()
    metadata = args.metadata_dir.expanduser().resolve()
    if workspace == PROJECT_ROOT or workspace in PROJECT_ROOT.parents:
        parser.error("Use a separate build workspace, not this project or one of its parent directories")
    if workspace == metadata or workspace in metadata.parents:
        parser.error("--metadata-dir must be outside --workspace")
    lock, manifest, projects = load_inputs()
    plan = {
        "status": "planned",
        "workspace": str(workspace),
        "metadata_dir": str(metadata),
        "project_count": len(projects),
        "manifest_sha256": lock["manifest_sha256"],
        "source_status": lock["status"],
        "repo_revision": lock["repo_tool"]["commit"],
        "jobs": args.jobs,
        "min_free_gib": args.min_free_gib,
        "notes": [
            "All project revisions and the repo launcher are pinned.",
            "Shallow sync; independent GBL/Fuchsia/LTP source projects are omitted.",
            "Bazel setup/patching and compilation are separate steps.",
            "45 GiB is a sync admission threshold, not a measured build-space guarantee.",
        ],
    }
    print(json.dumps(plan, indent=2), flush=True)
    if args.plan:
        return 0
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        raise RuntimeError("Actual builds require a Linux x86_64 runner")
    for command in ("git", "curl"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing required command: {command}")
    metadata.mkdir(parents=True, exist_ok=True)
    write_json(metadata / "sync-plan.json", plan)
    shutil.copyfile(LOCK_PATH, metadata / "source-lock.json")
    shutil.copyfile(manifest, metadata / "requested-manifest.xml")
    workspace.mkdir(parents=True, exist_ok=True)
    marker = workspace / MARKER
    if any(workspace.iterdir()):
        if not marker.exists() or json.loads(marker.read_text()).get("manifest_sha256") != lock["manifest_sha256"]:
            raise RuntimeError("Refusing nonempty/unmarked workspace or a different source lock")
    else:
        write_json(marker, {"manifest_sha256": lock["manifest_sha256"]})
    free = shutil.disk_usage(workspace).free / (1024 ** 3)
    print(f"Available source-workspace space: {free:.1f} GiB", flush=True)
    if free < args.min_free_gib:
        raise RuntimeError(f"Need at least {args.min_free_gib:g} GiB free before sync; have {free:.1f} GiB")
    record_versions(metadata)
    launcher = install_repo(lock, metadata)
    local_manifest = init_manifest_repository(manifest, metadata)
    started = time.time()
    run([
        str(launcher), "init", "-u", local_manifest.as_uri(), "-b", "main",
        "-m", "default.xml", "--depth=1", "--no-clone-bundle",
        f"--repo-url={lock['repo_tool']['url']}",
        f"--repo-rev={lock['repo_tool']['commit']}",
    ], cwd=workspace)
    actual_repo = run(
        ["git", "rev-parse", "HEAD"], cwd=workspace / ".repo/repo", capture=True,
    ).strip()
    if actual_repo != lock["repo_tool"]["commit"]:
        raise RuntimeError("repo tool checkout differs from pinned revision")
    verified = False
    try:
        run([
            str(launcher), "sync", "-c", f"-j{args.jobs}", "--no-tags",
            "--no-clone-bundle", "--optimized-fetch", "--retry-fetches=3",
            "--fail-fast",
        ], cwd=workspace)
        # Preserve repo's actual resolved manifest, including all linkfile and
        # copyfile directives, before any separate build-compatibility patches.
        run([
            str(launcher), "manifest", "-r", "-o",
            str(metadata / "resolved-manifest.xml"),
        ], cwd=workspace)
        verify_checkout(workspace, projects, metadata)
        verified = True
    finally:
        write_json(metadata / "sync-summary.json", {
            "elapsed_seconds": round(time.time() - started, 1),
            "free_gib_after_sync": round(shutil.disk_usage(workspace).free / (1024 ** 3), 2),
            "verification_complete": verified,
        })
    print(f"Sources verified; resolved manifest: {metadata / 'resolved-manifest.xml'}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"sync_sources: {exc}", file=sys.stderr)
        sys.exit(1)
