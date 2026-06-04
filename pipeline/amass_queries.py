#!/usr/bin/env python
"""
Build an Amass MCP execution plan from an LLM-authored research plan.

This script does not call Amass directly. Amass is an MCP backend available to
the Codex agent. The output of this script is the contract the agent follows:

1. read output/logs/amass_query_plan.json;
2. run each query through Amass BioMedCore;
3. save every raw MCP output with pipeline/amass_raw.py into
   output/logs/amass_raw/<exercise_id>/<query_id>.json;
4. stage raw files into output/logs/amass_results.json;
5. pass that JSON to generate_cards.py with --amass-json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from generate_cards import (
    ExerciseEntry,
    PROJECT_ROOT,
    load_exercises,
    looks_english,
    now_iso,
    write_json,
)
from research_plan import (
    ResearchPlanError,
    load_research_plan,
    query_specs_for_backend,
    research_plan_summary,
)


def unique_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def search_terms_for_entry(entry: ExerciseEntry) -> list[str]:
    return unique_strings([entry.exercise_name, *entry.aliases, entry.raw_name])


def build_amass_queries(
    entry: ExerciseEntry,
    research_plan: dict[str, Any],
    min_journal_quality_jufo: int,
    min_publication_date: str | None,
) -> list[dict[str, Any]]:
    queries = []
    for spec in query_specs_for_backend(research_plan, entry, "amass"):
        params: dict[str, Any] = {
            "query": spec["query"],
            "isRetracted": False,
            "minJournalQualityJufo": min_journal_quality_jufo,
        }
        if min_publication_date:
            params["minPublicationDate"] = min_publication_date
        queries.append(
            {
                "query_id": spec["query_id"],
                "query_scope": spec["query_scope"],
                "priority": spec["priority"],
                "match_class": spec["match_class"],
                "term_set": spec.get("term_set") or [],
                "movement_component_ids": spec.get("movement_component_ids") or [],
                "research_question_ids": spec.get("research_question_ids") or [],
                "intended_card_fields": spec.get("intended_card_fields") or [],
                "query_kind": spec.get("query_kind") or "llm_dynamic",
                "tool": "mcp__codex_apps__amass._search_amass_biomedcore_records",
                "parameters": params,
                "rationale": spec.get("rationale") or "",
            }
        )
    return queries


def build_plan(
    input_file: Path,
    exercises: list[ExerciseEntry],
    research_plan: dict[str, Any],
    min_journal_quality_jufo: int,
    min_publication_date: str | None,
) -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "input_file": str(input_file),
        "backend": "amass_biomedcore",
        "tool": "mcp__codex_apps__amass._search_amass_biomedcore_records",
        "instructions": [
            "Run every LLM-authored query in exercises[].queries through Amass BioMedCore in ascending priority order.",
            "Treat priority 1 specific_variation records as the strongest match; priority 2 and 3 records are supplemental.",
            "Use pipeline/amass_raw.py next to print missing MCP calls and canonical raw paths.",
            "Save each raw MCP response with pipeline/amass_raw.py save.",
            "Audit raw coverage with pipeline/amass_raw.py audit before staging.",
            "Stage raw files into output/logs/amass_results.json with pipeline/stage_amass_results.py.",
            "The staging step attaches query_id, query_scope, priority, and query as query_matches metadata.",
            "Do not remove PMID, DOI, amassId, abstract, hasFulltext, isRetracted, citationCount, or journalQualityJufo fields.",
        ],
        "query_strategy": "llm_dynamic_research_plan",
        "result_file": str(PROJECT_ROOT / "output" / "logs" / "amass_results.json"),
        "exercise_count": len(exercises),
        "exercises": [
            {
                "exercise_id": entry.exercise_id,
                "exercise_name": entry.exercise_name,
                "russian_name": entry.russian_name,
                "aliases": entry.aliases,
                "research_plan": research_plan_summary(research_plan, entry),
                "search_terms": search_terms_for_entry(entry),
                "warnings": entry_warnings(entry),
                "queries": build_amass_queries(entry, research_plan, min_journal_quality_jufo, min_publication_date),
            }
            for entry in exercises
        ],
    }


def entry_warnings(entry: ExerciseEntry) -> list[str]:
    warnings = []
    if not any(looks_english(term) for term in [entry.exercise_name, *entry.aliases, entry.raw_name]):
        warnings.append("No English search term detected; Amass/PubMed recall may be poor.")
    return warnings


def build_results_scaffold(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        item["exercise_id"]: {
            "exercise_id": item["exercise_id"],
            "exercise_name": item["exercise_name"],
            "russian_name": item["russian_name"],
            "aliases": item["aliases"],
            "query_strategy": "llm_dynamic_research_plan",
            "research_plan": item.get("research_plan") or {},
            "query_specs": [
                {
                    "query_id": query["query_id"],
                    "query_scope": query["query_scope"],
                    "priority": query["priority"],
                    "match_class": query["match_class"],
                    "term_set": query["term_set"],
                    "research_question_ids": query.get("research_question_ids") or [],
                    "intended_card_fields": query.get("intended_card_fields") or [],
                    "query": query["parameters"]["query"],
                    "rationale": query.get("rationale") or "",
                }
                for query in item["queries"]
            ],
            "queries_used": [query["parameters"]["query"] for query in item["queries"]],
            "results": [],
        }
        for item in plan["exercises"]
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Amass MCP query plan for an exercise list.")
    parser.add_argument("input_file", type=Path, help="Path to .txt, .md, or .csv input file.")
    parser.add_argument(
        "--research-plan",
        type=Path,
        required=True,
        help="LLM-authored research plan JSON. Search queries are not generated from local templates.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "amass_query_plan.json",
        help="Where to write the query plan JSON.",
    )
    parser.add_argument(
        "--scaffold",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "amass_results.scaffold.json",
        help="Where to write an empty amass_results scaffold JSON.",
    )
    parser.add_argument(
        "--min-journal-quality-jufo",
        type=int,
        default=1,
        choices=[0, 1, 2, 3],
        help="Amass minJournalQualityJufo filter.",
    )
    parser.add_argument(
        "--min-publication-date",
        help="Optional Amass minPublicationDate filter in YYYY-MM-DD format.",
    )
    parser.add_argument("--print", action="store_true", help="Print the plan JSON to stdout.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    input_file = args.input_file if args.input_file.is_absolute() else PROJECT_ROOT / args.input_file
    if not input_file.exists():
        raise SystemExit(f"Input file not found: {input_file}")

    exercises = load_exercises(input_file)
    if not exercises:
        raise SystemExit(f"No exercises found in input file: {input_file}")

    research_plan_path = args.research_plan if args.research_plan.is_absolute() else PROJECT_ROOT / args.research_plan
    try:
        research_plan = load_research_plan(research_plan_path)
    except ResearchPlanError as exc:
        raise SystemExit(str(exc)) from exc

    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    scaffold_path = args.scaffold if args.scaffold.is_absolute() else PROJECT_ROOT / args.scaffold
    plan = build_plan(
        input_file=input_file,
        exercises=exercises,
        research_plan=research_plan,
        min_journal_quality_jufo=args.min_journal_quality_jufo,
        min_publication_date=args.min_publication_date,
    )
    scaffold = build_results_scaffold(plan)
    write_json(output_path, plan)
    write_json(scaffold_path, scaffold)

    result = {
        "query_plan": str(output_path),
        "results_scaffold": str(scaffold_path),
        "exercise_count": len(exercises),
    }
    if args.print:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
