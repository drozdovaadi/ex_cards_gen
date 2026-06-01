#!/usr/bin/env python
"""
Build a standardized Amass MCP query plan from an exercise input file.

This script does not call Amass directly. Amass is an MCP backend available to
the Codex agent. The output of this script is the contract the agent follows:

1. read output/logs/amass_query_plan.json;
2. run each query through Amass BioMedCore;
3. save the merged MCP output as output/logs/amass_results.json;
4. pass that JSON to generate_cards.py with --amass-json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from generate_cards import ExerciseEntry, PROJECT_ROOT, load_exercises, looks_english, now_iso, write_json


DEFAULT_EVIDENCE_TERMS = [
    "biomechanics",
    "electromyography",
    "EMG",
    "kinematics",
    "kinetics",
    "muscle activation",
    "joint moment",
    "resistance training",
]

REVIEW_TERMS = [
    "review",
    "systematic review",
    "meta-analysis",
]

TECHNIQUE_TERMS = [
    "technique",
    "stance",
    "grip",
    "range of motion",
    "load",
    "fatigue",
]


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
    candidates = [entry.exercise_name, *entry.aliases, entry.raw_name]
    english_candidates = [candidate for candidate in candidates if looks_english(candidate)]
    return unique_strings(english_candidates or candidates)


def quoted(term: str) -> str:
    escaped = term.replace('"', '\\"')
    return f'"{escaped}"'


def build_query_text(exercise_terms: list[str], evidence_terms: list[str]) -> str:
    exercise_part = " OR ".join(quoted(term) for term in exercise_terms)
    evidence_part = " ".join(evidence_terms)
    if len(exercise_terms) > 1:
        return f"({exercise_part}) {evidence_part}"
    return f"{exercise_part} {evidence_part}"


def build_amass_queries(
    entry: ExerciseEntry,
    min_journal_quality_jufo: int,
    min_publication_date: str | None,
) -> list[dict[str, Any]]:
    terms = search_terms_for_entry(entry)
    query_specs = [
        ("biomechanics_core", DEFAULT_EVIDENCE_TERMS),
        ("review_synthesis", REVIEW_TERMS + ["biomechanics", "muscle activation", "resistance training"]),
        ("technique_and_load", TECHNIQUE_TERMS + ["biomechanics", "kinematics", "kinetics"]),
    ]

    queries = []
    for query_id, evidence_terms in query_specs:
        params: dict[str, Any] = {
            "query": build_query_text(terms, evidence_terms),
            "isRetracted": False,
            "minJournalQualityJufo": min_journal_quality_jufo,
        }
        if min_publication_date:
            params["minPublicationDate"] = min_publication_date
        queries.append(
            {
                "query_id": query_id,
                "tool": "mcp__codex_apps__amass._search_amass_biomedcore_records",
                "parameters": params,
                "rationale": query_rationale(query_id),
            }
        )
    return queries


def query_rationale(query_id: str) -> str:
    rationales = {
        "biomechanics_core": "Find direct biomechanics, EMG, kinematic, kinetic, and muscle activation evidence.",
        "review_synthesis": "Find reviews or synthesis papers to anchor broad claims and limitations.",
        "technique_and_load": "Find sources about technique variables, range of motion, load, fatigue, and movement mechanics.",
    }
    return rationales[query_id]


def build_plan(
    input_file: Path,
    exercises: list[ExerciseEntry],
    min_journal_quality_jufo: int,
    min_publication_date: str | None,
) -> dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "input_file": str(input_file),
        "backend": "amass_biomedcore",
        "tool": "mcp__codex_apps__amass._search_amass_biomedcore_records",
        "instructions": [
            "Run every query in exercises[].queries through Amass BioMedCore.",
            "Combine all unique Amass records per exercise.",
            "Save results as output/logs/amass_results.json using the scaffold shape.",
            "Do not remove PMID, DOI, amassId, abstract, hasFulltext, isRetracted, citationCount, or journalQualityJufo fields.",
        ],
        "result_file": str(PROJECT_ROOT / "output" / "logs" / "amass_results.json"),
        "exercise_count": len(exercises),
        "exercises": [
            {
                "exercise_id": entry.exercise_id,
                "exercise_name": entry.exercise_name,
                "russian_name": entry.russian_name,
                "aliases": entry.aliases,
                "search_terms": search_terms_for_entry(entry),
                "warnings": entry_warnings(entry),
                "queries": build_amass_queries(entry, min_journal_quality_jufo, min_publication_date),
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
            "queries_used": [query["parameters"]["query"] for query in item["queries"]],
            "results": [],
        }
        for item in plan["exercises"]
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Amass MCP query plan for an exercise list.")
    parser.add_argument("input_file", type=Path, help="Path to .txt, .md, or .csv input file.")
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

    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    scaffold_path = args.scaffold if args.scaffold.is_absolute() else PROJECT_ROOT / args.scaffold
    plan = build_plan(
        input_file=input_file,
        exercises=exercises,
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

