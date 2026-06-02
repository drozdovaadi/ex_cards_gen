#!/usr/bin/env python
"""
Manage raw Amass MCP responses for the exercise-card pipeline.

Amass BioMedCore is available to the Codex agent as an MCP tool, not as a
local Python API. This helper makes the agentic part reproducible:

- print the next missing MCP query from amass_query_plan.json;
- save the exact JSON response returned by Amass to the canonical raw path;
- audit raw file coverage and record counts before staging.

Canonical raw layout:

output/logs/amass_raw/<exercise_id>/<query_id>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from generate_cards import PROJECT_ROOT, now_iso, write_json
from stage_amass_results import extract_records, query_specs_for_exercise


DEFAULT_PLAN = PROJECT_ROOT / "output" / "logs" / "amass_query_plan.json"
DEFAULT_RAW_DIR = PROJECT_ROOT / "output" / "logs" / "amass_raw"
DEFAULT_MANIFEST = PROJECT_ROOT / "output" / "logs" / "amass_raw_manifest.json"
DEFAULT_AUDIT = PROJECT_ROOT / "output" / "logs" / "amass_raw_audit.json"


class AmassRawError(RuntimeError):
    pass


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AmassRawError(f"Invalid JSON in {path}: {exc}") from exc


def parse_json_text(text: str, label: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AmassRawError(f"Invalid JSON payload for {label}: {exc}") from exc


def canonical_raw_path(raw_dir: Path, exercise_id: str, query_id: str) -> Path:
    return raw_dir / exercise_id / f"{query_id}.json"


def stable_json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_plan_items(
    plan: dict[str, Any],
    exercise_id: str | None = None,
    limit_exercises: int | None = None,
) -> list[dict[str, Any]]:
    items = []
    exercise_count = 0
    for exercise in plan.get("exercises", []):
        if exercise_id and exercise.get("exercise_id") != exercise_id:
            continue
        exercise_count += 1
        if limit_exercises is not None and exercise_count > limit_exercises:
            break
        for query in exercise.get("queries", []):
            params = query.get("parameters") or {}
            items.append(
                {
                    "exercise_id": exercise.get("exercise_id"),
                    "exercise_name": exercise.get("exercise_name"),
                    "russian_name": exercise.get("russian_name"),
                    "query_id": query.get("query_id"),
                    "query_scope": query.get("query_scope"),
                    "priority": query.get("priority"),
                    "match_class": query.get("match_class"),
                    "tool": query.get("tool"),
                    "parameters": params,
                    "query": params.get("query"),
                    "rationale": query.get("rationale"),
                }
            )
    return items


def find_query(plan: dict[str, Any], exercise_id: str, query_id: str) -> dict[str, Any]:
    for item in iter_plan_items(plan, exercise_id=exercise_id):
        if item["query_id"] == query_id:
            return item
    raise AmassRawError(f"Query not found in plan: {exercise_id}/{query_id}")


def read_payload(args: argparse.Namespace) -> Any:
    if args.payload_file:
        path = resolve_project_path(args.payload_file)
        return load_json(path)

    text = sys.stdin.read()
    if not text.strip():
        raise AmassRawError("No payload received. Pipe JSON on stdin or pass --payload-file.")
    return parse_json_text(text, label="stdin")


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "generated_at": now_iso(),
            "updated_at": now_iso(),
            "raw_layout": "output/logs/amass_raw/<exercise_id>/<query_id>.json",
            "captures": [],
        }
    data = load_json(path)
    if not isinstance(data, dict):
        raise AmassRawError(f"Manifest must be an object: {path}")
    data.setdefault("captures", [])
    return data


@contextmanager
def manifest_lock(manifest_path: Path, timeout_seconds: float = 120.0):
    lock_path = manifest_path.with_suffix(manifest_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    handle: int | None = None
    while handle is None:
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise AmassRawError(f"Timed out waiting for manifest lock: {lock_path}")
            time.sleep(0.2)
    try:
        yield
    finally:
        os.close(handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def update_manifest(manifest_path: Path, capture: dict[str, Any]) -> None:
    with manifest_lock(manifest_path):
        manifest = load_manifest(manifest_path)
        captures = [
            item
            for item in manifest.get("captures", [])
            if not (
                item.get("exercise_id") == capture["exercise_id"]
                and item.get("query_id") == capture["query_id"]
            )
        ]
        captures.append(capture)
        manifest["captures"] = sorted(
            captures,
            key=lambda item: (item.get("exercise_id") or "", item.get("priority") or 99, item.get("query_id") or ""),
        )
        manifest["updated_at"] = now_iso()
        write_json(manifest_path, manifest)



def command_next(args: argparse.Namespace) -> int:
    plan = load_json(resolve_project_path(args.plan))
    raw_dir = resolve_project_path(args.raw_dir)
    items = iter_plan_items(plan, exercise_id=args.exercise_id, limit_exercises=args.limit_exercises)

    missing = []
    for item in items:
        path = canonical_raw_path(raw_dir, item["exercise_id"], item["query_id"])
        if path.exists():
            continue
        missing.append(
            {
                **item,
                "raw_path": str(path),
                "save_command": (
                    "python pipeline\\amass_raw.py save "
                    f"--exercise-id {item['exercise_id']} --query-id {item['query_id']}"
                ),
            }
        )

    output = {
        "generated_at": now_iso(),
        "raw_dir": str(raw_dir),
        "missing_count": len(missing),
        "items": missing[: args.limit],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if args.fail_if_missing and missing else 0


def command_save(args: argparse.Namespace) -> int:
    plan_path = resolve_project_path(args.plan)
    raw_dir = resolve_project_path(args.raw_dir)
    manifest_path = resolve_project_path(args.manifest)
    plan = load_json(plan_path)
    query_item = find_query(plan, args.exercise_id, args.query_id)
    payload = read_payload(args)
    records = extract_records(payload)

    raw_path = canonical_raw_path(raw_dir, args.exercise_id, args.query_id)
    if raw_path.exists() and not args.force:
        raise AmassRawError(f"Raw file already exists. Use --force to overwrite: {raw_path}")

    data = stable_json_bytes(payload)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)

    capture = {
        "saved_at": now_iso(),
        "exercise_id": args.exercise_id,
        "exercise_name": query_item.get("exercise_name"),
        "query_id": args.query_id,
        "query_scope": query_item.get("query_scope"),
        "priority": query_item.get("priority"),
        "match_class": query_item.get("match_class"),
        "tool": query_item.get("tool"),
        "parameters": query_item.get("parameters"),
        "raw_path": str(raw_path),
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "record_count": len(records),
        "status": "saved",
    }
    update_manifest(manifest_path, capture)
    print(json.dumps(capture, ensure_ascii=False, indent=2))
    return 0


def audit_raw_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "record_count": 0, "error": "missing"}
    try:
        payload = load_json(path)
        records = extract_records(payload)
        data = path.read_bytes()
        return {
            "exists": True,
            "record_count": len(records),
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "error": None,
        }
    except Exception as exc:
        return {"exists": True, "record_count": 0, "error": str(exc)}


def build_audit(
    plan: dict[str, Any],
    raw_dir: Path,
    exercise_id: str | None = None,
    limit_exercises: int | None = None,
) -> dict[str, Any]:
    items = []
    for item in iter_plan_items(plan, exercise_id=exercise_id, limit_exercises=limit_exercises):
        raw_path = canonical_raw_path(raw_dir, item["exercise_id"], item["query_id"])
        audit = audit_raw_file(raw_path)
        items.append(
            {
                "exercise_id": item["exercise_id"],
                "exercise_name": item["exercise_name"],
                "query_id": item["query_id"],
                "query_scope": item["query_scope"],
                "priority": item["priority"],
                "raw_path": str(raw_path),
                **audit,
            }
        )

    missing = [item for item in items if not item["exists"]]
    invalid = [item for item in items if item.get("error") and item["exists"]]
    return {
        "generated_at": now_iso(),
        "raw_dir": str(raw_dir),
        "expected_query_count": len(items),
        "present_query_count": sum(1 for item in items if item["exists"] and not item.get("error")),
        "missing_query_count": len(missing),
        "invalid_query_count": len(invalid),
        "record_count": sum(item.get("record_count") or 0 for item in items),
        "items": items,
    }


def command_audit(args: argparse.Namespace) -> int:
    plan = load_json(resolve_project_path(args.plan))
    raw_dir = resolve_project_path(args.raw_dir)
    audit = build_audit(
        plan=plan,
        raw_dir=raw_dir,
        exercise_id=args.exercise_id,
        limit_exercises=args.limit_exercises,
    )
    if args.output:
        write_json(resolve_project_path(args.output), audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if args.require_complete and (audit["missing_query_count"] or audit["invalid_query_count"]):
        return 2
    return 0


def command_manifest(args: argparse.Namespace) -> int:
    plan = load_json(resolve_project_path(args.plan))
    raw_dir = resolve_project_path(args.raw_dir)
    items = []
    for item in iter_plan_items(plan, exercise_id=args.exercise_id, limit_exercises=args.limit_exercises):
        raw_path = canonical_raw_path(raw_dir, item["exercise_id"], item["query_id"])
        items.append({**item, "raw_path": str(raw_path), "exists": raw_path.exists()})
    manifest = {
        "generated_at": now_iso(),
        "plan": str(resolve_project_path(args.plan)),
        "raw_dir": str(raw_dir),
        "query_count": len(items),
        "items": items,
    }
    if args.output:
        write_json(resolve_project_path(args.output), manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage raw Amass MCP responses.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_plan_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--plan", type=Path, default=DEFAULT_PLAN, help="Path to amass_query_plan.json.")
        subparser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Raw Amass directory.")
        subparser.add_argument("--exercise-id", help="Limit to one exercise_id.")
        subparser.add_argument("--limit-exercises", type=int, help="Limit to the first N matching exercises.")

    manifest = subparsers.add_parser("manifest", help="Print/write the expected raw Amass query manifest.")
    add_plan_args(manifest)
    manifest.add_argument("--output", type=Path, help="Optional JSON output path.")
    manifest.set_defaults(func=command_manifest)

    next_query = subparsers.add_parser("next", help="Print the next missing raw Amass MCP query.")
    add_plan_args(next_query)
    next_query.add_argument("--limit", type=int, default=1, help="Number of missing queries to print.")
    next_query.add_argument("--fail-if-missing", action="store_true", help="Exit 1 when missing queries exist.")
    next_query.set_defaults(func=command_next)

    save = subparsers.add_parser("save", help="Save one raw Amass MCP JSON response.")
    save.add_argument("--plan", type=Path, default=DEFAULT_PLAN, help="Path to amass_query_plan.json.")
    save.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Raw Amass directory.")
    save.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Capture manifest path.")
    save.add_argument("--exercise-id", required=True, help="Exercise ID from the query plan.")
    save.add_argument("--query-id", required=True, help="Query ID from the query plan.")
    save.add_argument("--payload-file", type=Path, help="Read Amass JSON payload from this file.")
    save.add_argument("--force", action="store_true", help="Overwrite an existing raw file.")
    save.set_defaults(func=command_save)

    audit = subparsers.add_parser("audit", help="Audit raw Amass MCP coverage and parseability.")
    add_plan_args(audit)
    audit.add_argument("--output", type=Path, default=DEFAULT_AUDIT, help="Audit JSON output path.")
    audit.add_argument("--require-complete", action="store_true", help="Exit 2 if raw files are missing or invalid.")
    audit.set_defaults(func=command_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    try:
        return args.func(args)
    except AmassRawError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
