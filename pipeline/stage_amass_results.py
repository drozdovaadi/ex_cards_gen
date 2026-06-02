#!/usr/bin/env python
"""
Stage Amass MCP query responses into the project amass_results.json shape.

Amass is called from the Codex chat as an MCP tool, not from local Python.
This script standardizes the saved MCP outputs after those calls:

- attach query provenance to every record through query_matches;
- deduplicate records per exercise by Amass ID, PMID, DOI, PMCID, or title;
- preserve the scaffold shape expected by generate_cards.py.

Preferred raw layout:

output/logs/amass_raw/<exercise_id>/<query_id>.json

The script also accepts legacy aggregate files through --input. If a legacy
record lacks query_matches, the script infers the closest query scope from
title/abstract text and marks that match as inferred_from_record_text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from generate_cards import PROJECT_ROOT, contains_normalized_phrase, normalize_title, now_iso, write_json


class AmassStageError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AmassStageError(f"Invalid JSON in {path}: {exc}") from exc


def is_record_like(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(value.get(field) for field in ["amassId", "pmid", "doi", "pmcid", "title", "abstract"])


def parse_embedded_json_text(text: str) -> Any | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, str):
        embedded = parse_embedded_json_text(payload)
        return extract_records(embedded) if embedded is not None else []

    if isinstance(payload, list):
        records: list[dict[str, Any]] = []
        for item in payload:
            records.extend(extract_records(item))
        return records

    if not isinstance(payload, dict):
        return []

    if is_record_like(payload):
        return [payload]

    for field in ["results", "records", "items", "data"]:
        value = payload.get(field)
        if value is not None:
            records = extract_records(value)
            if records:
                return records

    content = payload.get("content")
    if isinstance(content, list):
        records: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                records.extend(extract_records(item["text"]))
            else:
                records.extend(extract_records(item))
        return records

    return []


def query_specs_for_exercise(exercise: dict[str, Any]) -> list[dict[str, Any]]:
    specs = []
    for query in exercise.get("queries", []):
        params = query.get("parameters") or {}
        specs.append(
            {
                "query_id": query.get("query_id"),
                "query_scope": query.get("query_scope"),
                "priority": query.get("priority"),
                "match_class": query.get("match_class"),
                "term_set": query.get("term_set") or [],
                "query": params.get("query"),
            }
        )
    return specs


def query_match_from_spec(spec: dict[str, Any], match_source: str) -> dict[str, Any]:
    return {
        "query_id": spec.get("query_id"),
        "query_scope": spec.get("query_scope"),
        "priority": coerce_priority(spec.get("priority")),
        "match_class": spec.get("match_class"),
        "term_set": spec.get("term_set") or [],
        "query": spec.get("query"),
        "match_source": match_source,
    }


def coerce_priority(value: Any, default: int = 99) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_query_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    seen = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        query_id = str(match.get("query_id") or "")
        query_scope = str(match.get("query_scope") or "")
        query = str(match.get("query") or "")
        priority = coerce_priority(match.get("priority"))
        key = (query_id, query_scope, str(priority), query)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "query_id": query_id,
                "query_scope": query_scope,
                "priority": priority,
                **({"match_class": match.get("match_class")} if match.get("match_class") else {}),
                **({"term_set": match.get("term_set")} if match.get("term_set") else {}),
                **({"query": query} if query else {}),
                **({"match_source": match.get("match_source")} if match.get("match_source") else {}),
                **({"term_matches": match.get("term_matches")} if match.get("term_matches") else {}),
            }
        )
    return sorted(normalized, key=lambda item: coerce_priority(item.get("priority")))


def record_text(record: dict[str, Any]) -> str:
    return normalize_title(" ".join([record.get("title") or "", record.get("abstract") or ""]))


def infer_query_matches(record: dict[str, Any], query_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    text = record_text(record)
    if not text:
        return []

    matches = []
    matched_scopes = set()
    for spec in sorted(query_specs, key=lambda item: coerce_priority(item.get("priority"))):
        scope = spec.get("query_scope")
        if scope in matched_scopes:
            continue
        term_matches = [
            term
            for term in spec.get("term_set") or []
            if contains_normalized_phrase(text, normalize_title(term))
        ]
        if not term_matches:
            continue
        match = query_match_from_spec(spec, match_source="inferred_from_record_text")
        match["term_matches"] = term_matches
        matches.append(match)
        matched_scopes.add(scope)
    return matches


def unscoped_query_match() -> dict[str, Any]:
    return {
        "query_id": "unscoped_amass_import",
        "query_scope": "unscoped",
        "priority": 99,
        "match_source": "unscoped_import",
    }


def ensure_query_matches(
    record: dict[str, Any],
    query_specs: list[dict[str, Any]],
    direct_query_spec: dict[str, Any] | None,
    infer_legacy_matches: bool,
) -> dict[str, Any]:
    staged = dict(record)
    matches = []
    raw_matches = staged.get("query_matches")
    if isinstance(raw_matches, list):
        matches.extend(match for match in raw_matches if isinstance(match, dict))

    if staged.get("query_id") or staged.get("query_scope"):
        matches.append(
            {
                "query_id": staged.get("query_id"),
                "query_scope": staged.get("query_scope"),
                "priority": staged.get("priority"),
                "query": staged.get("query"),
                "match_source": "record_fields",
            }
        )

    if direct_query_spec is not None:
        matches.append(query_match_from_spec(direct_query_spec, match_source="raw_query_file"))

    if not matches and infer_legacy_matches:
        matches.extend(infer_query_matches(staged, query_specs))

    if not matches:
        matches.append(unscoped_query_match())

    staged["query_matches"] = normalize_query_matches(matches)
    return staged


def record_dedupe_key(record: dict[str, Any]) -> str:
    for field in ["amassId", "pmid", "doi", "pmcid"]:
        value = record.get(field)
        if value:
            return f"{field}:{str(value).lower()}"
    title = normalize_title(record.get("title") or "")
    if title:
        return f"title:{title}"
    digest = hashlib.sha1(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def merge_records(existing: dict[str, Any], new_record: dict[str, Any]) -> None:
    existing["query_matches"] = normalize_query_matches(
        [*(existing.get("query_matches") or []), *(new_record.get("query_matches") or [])]
    )
    for field, value in new_record.items():
        if field == "query_matches":
            continue
        if field == "hasFulltext":
            existing[field] = bool(existing.get(field) or value)
            continue
        if field == "isRetracted":
            existing[field] = bool(existing.get(field) or value)
            continue
        if field == "authors" and isinstance(value, list):
            if len(value) > len(existing.get(field) or []):
                existing[field] = value
            continue
        if not existing.get(field) and value:
            existing[field] = value


def add_record(
    staged_results: dict[str, dict[str, Any]],
    exercise_id: str,
    record: dict[str, Any],
) -> None:
    bucket = staged_results[exercise_id].setdefault("_dedupe", {})
    key = record_dedupe_key(record)
    existing = bucket.get(key)
    if existing is None:
        bucket[key] = dict(record)
    else:
        merge_records(existing, record)


def raw_file_index(raw_dirs: list[Path], plan: dict[str, Any]) -> dict[tuple[str, str], list[Path]]:
    index: dict[tuple[str, str], list[Path]] = {}
    exercises = plan.get("exercises", [])
    for raw_dir in raw_dirs:
        if not raw_dir.exists():
            raise AmassStageError(f"Raw directory not found: {raw_dir}")
        for path in sorted(raw_dir.rglob("*.json")):
            normalized_path = path.relative_to(raw_dir).as_posix().lower()
            for exercise in exercises:
                exercise_id = exercise["exercise_id"]
                if exercise_id.lower() not in normalized_path:
                    continue
                for spec in query_specs_for_exercise(exercise):
                    query_id = str(spec.get("query_id") or "")
                    if query_id and query_id.lower() in normalized_path:
                        index.setdefault((exercise_id, query_id), []).append(path)
    return index


def build_empty_output(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    staged = {}
    for exercise in plan.get("exercises", []):
        query_specs = query_specs_for_exercise(exercise)
        staged[exercise["exercise_id"]] = {
            "exercise_id": exercise["exercise_id"],
            "exercise_name": exercise["exercise_name"],
            "russian_name": exercise["russian_name"],
            "aliases": exercise.get("aliases") or [],
            "query_strategy": "tiered_specific_then_family_then_pattern",
            "query_specs": query_specs,
            "queries_used": [spec["query"] for spec in query_specs if spec.get("query")],
            "results": [],
            "_dedupe": {},
        }
    return staged


def stage_raw_query_files(
    staged: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    raw_dirs: list[Path],
) -> int:
    if not raw_dirs:
        return 0

    index = raw_file_index(raw_dirs, plan)
    loaded_file_count = 0
    for exercise in plan.get("exercises", []):
        exercise_id = exercise["exercise_id"]
        query_specs = query_specs_for_exercise(exercise)
        for spec in query_specs:
            query_id = str(spec.get("query_id") or "")
            for path in index.get((exercise_id, query_id), []):
                loaded_file_count += 1
                payload = load_json(path)
                for record in extract_records(payload):
                    staged_record = ensure_query_matches(
                        record=record,
                        query_specs=query_specs,
                        direct_query_spec=spec,
                        infer_legacy_matches=False,
                    )
                    add_record(staged, exercise_id, staged_record)
    return loaded_file_count


def stage_aggregate_inputs(
    staged: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    input_paths: list[Path],
    infer_legacy_matches: bool,
) -> int:
    loaded_file_count = 0
    exercise_by_id = {exercise["exercise_id"]: exercise for exercise in plan.get("exercises", [])}
    for path in input_paths:
        if not path.exists():
            raise AmassStageError(f"Input file not found: {path}")
        payload = load_json(path)
        loaded_file_count += 1

        if isinstance(payload, dict):
            for exercise_id, exercise in exercise_by_id.items():
                if exercise_id not in payload:
                    continue
                query_specs = query_specs_for_exercise(exercise)
                exercise_payload = payload[exercise_id]
                for record in extract_records(exercise_payload):
                    staged_record = ensure_query_matches(
                        record=record,
                        query_specs=query_specs,
                        direct_query_spec=None,
                        infer_legacy_matches=infer_legacy_matches,
                    )
                    add_record(staged, exercise_id, staged_record)
            continue

        records = extract_records(payload)
        for record in records:
            exercise_id = record.get("exercise_id")
            if exercise_id not in exercise_by_id:
                continue
            query_specs = query_specs_for_exercise(exercise_by_id[exercise_id])
            staged_record = ensure_query_matches(
                record=record,
                query_specs=query_specs,
                direct_query_spec=None,
                infer_legacy_matches=infer_legacy_matches,
            )
            add_record(staged, exercise_id, staged_record)
    return loaded_file_count


def finalize_output(staged: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output = {}
    for exercise_id, payload in staged.items():
        deduped = payload.pop("_dedupe", {})
        results = sorted(
            deduped.values(),
            key=lambda record: (
                min((coerce_priority(match.get("priority")) for match in record.get("query_matches") or []), default=99),
                record.get("publicationDate") is None,
                str(record.get("title") or ""),
            ),
        )
        payload["results"] = results
        output[exercise_id] = payload
    return output


def build_report(output_path: Path, staged_output: dict[str, Any], loaded_files: int) -> dict[str, Any]:
    exercise_reports = []
    for exercise_id, payload in staged_output.items():
        results = payload.get("results") or []
        unscoped_count = sum(
            1
            for record in results
            if any(match.get("query_scope") == "unscoped" for match in record.get("query_matches") or [])
        )
        inferred_count = sum(
            1
            for record in results
            if any(match.get("match_source") == "inferred_from_record_text" for match in record.get("query_matches") or [])
        )
        exercise_reports.append(
            {
                "exercise_id": exercise_id,
                "source_count": len(results),
                "inferred_query_match_count": inferred_count,
                "unscoped_query_match_count": unscoped_count,
            }
        )
    return {
        "generated_at": now_iso(),
        "output": str(output_path),
        "loaded_input_files": loaded_files,
        "exercise_count": len(staged_output),
        "source_count": sum(item["source_count"] for item in exercise_reports),
        "exercises": exercise_reports,
    }


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage Amass MCP raw responses into amass_results.json.")
    parser.add_argument(
        "--plan",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "amass_query_plan.json",
        help="Path to amass_query_plan.json.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        action="append",
        default=[],
        help=(
            "Directory containing per-query raw Amass MCP JSON files. "
            "Use output/logs/amass_raw/<exercise_id>/<query_id>.json."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        default=[],
        help="Legacy aggregate Amass JSON to merge. Records without query_matches are inferred from text.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "amass_results.json",
        help="Where to write staged Amass results JSON.",
    )
    parser.add_argument(
        "--no-infer-legacy-matches",
        action="store_true",
        help="Do not infer query scope for aggregate records that lack query_matches.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)

    plan_path = resolve_project_path(args.plan)
    output_path = resolve_project_path(args.output)
    raw_dirs = [resolve_project_path(path) for path in args.raw_dir]
    input_paths = [resolve_project_path(path) for path in args.input]
    if not raw_dirs and not input_paths:
        raise SystemExit("Provide at least one --raw-dir or --input.")
    if not plan_path.exists():
        raise SystemExit(f"Amass query plan not found: {plan_path}")

    plan = load_json(plan_path)
    staged = build_empty_output(plan)
    loaded_files = stage_raw_query_files(staged, plan, raw_dirs)
    loaded_files += stage_aggregate_inputs(
        staged=staged,
        plan=plan,
        input_paths=input_paths,
        infer_legacy_matches=not args.no_infer_legacy_matches,
    )
    staged_output = finalize_output(staged)
    write_json(output_path, staged_output)
    report = build_report(output_path, staged_output, loaded_files)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
