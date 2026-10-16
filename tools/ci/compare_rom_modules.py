#!/usr/bin/env python3
"""Compare declared ROM load requests with verify_dist module names (informational).

Read only the two inputs and create exactly the requested new output JSON. The
output parent directory must exist. Existing output files are never replaced.
Missing names and a failed upstream component-check status do not change the
exit code; invalid inputs or an unwritable/existing output are command errors.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def read_json(path):
    payload = path.read_bytes()
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value, {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest()}


def unique(values):
    return list(dict.fromkeys(values))


def normalize_modinfo_name(value):
    if not isinstance(value, str) or not value or any(c.isspace() for c in value) or "/" in value:
        raise ValueError(f"Expected a nonempty bare module-info name: {value!r}")
    return value.replace("-", "_")


def entry_name(entry):
    if not isinstance(entry, dict):
        raise ValueError("Each baseline load entry must be an object")
    path = entry.get("module_path")
    if not isinstance(path, str) or not path.endswith(".ko"):
        raise ValueError(f"Expected a baseline .ko module_path: {path!r}")
    name = normalize_modinfo_name(PurePosixPath(path).name[:-3])
    if entry.get("normalized_module_name") != name:
        raise ValueError(f"Inconsistent baseline normalized name: {path!r}")
    for key in ("source_line", "order"):
        if type(entry.get(key)) is not int or entry[key] < 1:
            raise ValueError(f"Baseline entry needs a positive {key}: {path!r}")
    return name


def compare_entries(entries, built_names):
    names = unique(entry_name(entry) for entry in entries)
    matched = [name for name in names if name in built_names]
    missing = [name for name in names if name not in built_names]
    # Preserve the original objects, source line numbers, order and duplicates.
    missing_entries = [entry for entry in entries if entry_name(entry) not in built_names]
    return {
        "requested_entry_count": len(entries),
        "requested_unique_name_count": len(names),
        "matched_entry_count": len(entries) - len(missing_entries),
        "matched_unique_name_count": len(matched),
        "missing_entry_count": len(missing_entries),
        "missing_unique_name_count": len(missing),
        "matched_normalized_module_names": matched,
        "missing_normalized_module_names": missing,
        "missing_ordered_entries": missing_entries,
    }


def compare(report, baseline):
    # verify_dist.module_info() returns name fields inside report["modules"].
    # Source filenames are deliberately not used as a name fallback.
    modules = report.get("modules", [])
    if not isinstance(modules, list):
        raise ValueError("Expected report.modules to be a list")
    built_names = set()
    for module in modules:
        if not isinstance(module, dict) or not isinstance(module.get("name"), list):
            raise ValueError("Each report.modules entry must have a name list")
        built_names.update(normalize_modinfo_name(name) for name in module["name"])

    stages = baseline.get("load_stages")
    sources = baseline.get("sources")
    if not isinstance(stages, list) or not isinstance(sources, dict):
        raise ValueError("Expected baseline.load_stages list and baseline.sources object")
    comparisons, all_entries, all_oplus_entries, seen_ids = [], [], [], set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise ValueError("Each baseline load stage must be an object")
        stage_id, source_id = stage.get("id"), stage.get("source_id")
        entries = stage.get("ordered_entries")
        if not isinstance(stage_id, str) or not stage_id or stage_id in seen_ids:
            raise ValueError(f"Expected a unique nonempty stage id: {stage_id!r}")
        seen_ids.add(stage_id)
        if not isinstance(source_id, str) or source_id not in sources:
            raise ValueError(f"Missing source metadata for stage {stage_id!r}")
        if not isinstance(entries, list):
            raise ValueError(f"Expected ordered_entries list for stage {stage_id!r}")
        for position, entry in enumerate(entries, 1):
            entry_name(entry)
            if entry["order"] != position:
                raise ValueError(f"Non-sequential order in stage {stage_id!r}")
        oplus_entries = [entry for entry in entries if entry_name(entry).startswith("oplus_")]
        comparison = {
            "id": stage_id,
            "source_id": source_id,
            "source": sources[source_id],
            "purpose": stage.get("purpose"),
            **compare_entries(entries, built_names),
            "oplus_named_requests": {
                **compare_entries(oplus_entries, built_names),
                "ordered_entries": oplus_entries,
            },
        }
        comparisons.append(comparison)
        all_entries.extend(entries)
        all_oplus_entries.extend(oplus_entries)

    summary = compare_entries(all_entries, built_names)
    # Global name lists/counts are useful, but source lines must be interpreted
    # within the stage; missing entry details live in load_stages instead.
    summary.pop("missing_ordered_entries")
    oplus_summary = compare_entries(all_oplus_entries, built_names)
    oplus_summary.pop("missing_ordered_entries")
    passed = report.get("status") == "component_checks_passed"
    return {
        "schema_version": 1,
        "status": "informational_comparison_completed",
        "purpose": "Compare original-ROM declared module-load names against statically inspected component artifact module-info names.",
        "ci_policy": {
            "mode": "informational",
            "hard_failure_gate": False,
            "missing_names_affect_exit_code": False,
        },
        "input_report_status": report.get("status"),
        "input_report_component_checks_passed": passed,
        "input_report_status_note": (
            "Input report declares component_checks_passed; this comparison adds no build, integration or runtime validation."
            if passed else
            "Input report does not declare component_checks_passed. Names below describe only entries available in that report; this comparison does not establish a successful or complete component build."
        ),
        "name_matching": {
            "artifact_source": "report.modules[].name[] as produced by verify_dist.module_info(); no fallback to module source basenames",
            "artifact_normalization": "Replace hyphens with underscores in each bare module-info name; preserve case.",
            "baseline_normalization": "POSIX basename of module_path, remove trailing .ko, replace hyphens with underscores; verify against normalized_module_name.",
            "oplus_selection": "Normalized requested names starting with oplus_. This is a name-based group and does not prove vendor exclusivity or functional purpose.",
            "list_order": "Names retain first request occurrence; missing_ordered_entries retains every original request, including duplicates and source_line/order. Stage ordering is not a claimed runtime sequence.",
        },
        "limitations": [
            "A normalized name match establishes only reported name presence, not ABI/KMI, symbol/version compatibility, dependency closure, module load order correctness or equivalent functionality.",
            "Missing names may reflect built-in drivers, renaming, replacements, inactive multi-platform ROM entries, incomplete artifacts or missing drivers; each requires manual review. No built-in or rename equivalence is inferred.",
            "The original load lists are declarations, not runtime load evidence. No successful boot, runtime module load, device-tree selection, HAL/firmware compatibility or hardware operation is verified.",
            "This comparison does not inspect modules.dep, resolve a dependency graph, inspect binary symbols or change the input component-check report.",
        ],
        "artifact_module_entry_count": len(modules),
        "artifact_unique_normalized_module_name_count": len(built_names),
        "artifact_unique_normalized_module_names": sorted(built_names),
        "summary": summary,
        "oplus_named_requests_summary": oplus_summary,
        "load_stages": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True,
                        help="Existing verify_dist component-checks.json")
    parser.add_argument("--baseline", type=Path,
                        default=Path(__file__).resolve().parents[2] / "ci/rom-module-load-baseline.json")
    parser.add_argument("--out", type=Path, required=True,
                        help="New JSON file; parent must exist; existing files are never overwritten")
    args = parser.parse_args()
    try:
        report, report_source = read_json(args.report)
        baseline, baseline_source = read_json(args.baseline)
        comparison = compare(report, baseline)
        comparison["inputs"] = {"report": report_source, "baseline": baseline_source}
        payload = json.dumps(comparison, ensure_ascii=False, indent=2) + "\n"
        with args.out.open("x", encoding="utf-8") as destination:
            destination.write(payload)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    summary = comparison["summary"]
    print(f"Informational comparison saved to {args.out}; "
          f"input status={comparison['input_report_status']!r}; "
          f"matched={summary['matched_unique_name_count']}, "
          f"missing for review={summary['missing_unique_name_count']} unique requested names.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
