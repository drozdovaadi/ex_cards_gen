#!/usr/bin/env python
"""
Unified entry point for the exercise-card generation pipeline.

Supported inputs:
- --input path/to/exercises.txt
- --exercise "Name" --alias "Alias" --notes "Technique notes"
- --inline "exercise 1\nexercise 2"
- --stdin
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from generate_cards import PROJECT_ROOT, load_exercises, now_iso, resolve_project_path, write_json
from movement_decomposition import build_movement_decomposition, decomposition_summary


class RunGenerationError(RuntimeError):
    pass


def safe_run_id() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def resolve_input_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def write_run_input(run_id: str, label: str, content: str) -> Path:
    output_path = PROJECT_ROOT / "output" / "logs" / "run_inputs" / f"{run_id}_{label}.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content.strip() + "\n", encoding="utf-8")
    return output_path


def exercise_line(name: str, aliases: list[str], notes: str) -> str:
    parts = [name, *aliases]
    if notes:
        parts.append(f"notes: {notes}")
    return " | ".join(part for part in parts if part)


def materialize_input(args: argparse.Namespace, run_id: str) -> Path:
    if args.input:
        input_path = resolve_input_path(args.input)
        if not input_path.exists():
            raise RunGenerationError(f"Input file not found: {input_path}")
        return input_path
    if args.exercise:
        return write_run_input(run_id, "single", exercise_line(args.exercise, args.alias or [], args.notes or ""))
    if args.inline:
        return write_run_input(run_id, "inline", args.inline)
    if args.stdin:
        raw = sys.stdin.buffer.read()
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw.decode("cp1251")
        if not content.strip():
            raise RunGenerationError("--stdin was selected, but stdin is empty.")
        return write_run_input(run_id, "stdin", content)
    raise RunGenerationError("One input mode is required.")


def command_to_string(command: list[str]) -> str:
    return " ".join(f'"{part}"' if re.search(r"\s", part) else part for part in command)


def run_command(command: list[str]) -> dict[str, Any]:
    started_at = now_iso()
    proc = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    log = {
        "command": command,
        "command_text": command_to_string(command),
        "started_at": started_at,
        "finished_at": now_iso(),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0:
        raise RunGenerationError(
            f"Pipeline command failed with exit code {proc.returncode}: {command_to_string(command)}\n{proc.stderr}"
        )
    return log


def build_dry_run_report(input_path: Path) -> dict[str, Any]:
    exercises = load_exercises(input_path)
    return {
        "generated_at": now_iso(),
        "mode": "dry_run",
        "input_file": str(input_path),
        "exercise_count": len(exercises),
        "exercises": [
            {
                "exercise_id": entry.exercise_id,
                "raw_name": entry.raw_name,
                "exercise_name": entry.exercise_name,
                "russian_name": entry.russian_name,
                "aliases": entry.aliases,
                "notes": entry.notes,
                "movement_decomposition_summary": decomposition_summary(build_movement_decomposition(entry)),
            }
            for entry in exercises
        ],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the full exercise-card generation pipeline.")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=Path, help="Path to .txt, .md, or .csv exercise input.")
    input_group.add_argument("--exercise", help="Single exercise name.")
    input_group.add_argument("--inline", help="Inline exercise list. Lines can use: ru name | English alias | alias 2.")
    input_group.add_argument("--stdin", action="store_true", help="Read exercise list from stdin.")
    parser.add_argument("--alias", action="append", default=[], help="Alias for --exercise. Can be passed multiple times.")
    parser.add_argument("--notes", default="", help="Technique notes for --exercise.")
    parser.add_argument("--retmax", type=int, default=10, help="Maximum PubMed results per exercise.")
    parser.add_argument("--cards-dir", type=Path, default=Path("output") / "exercise_cards")
    parser.add_argument("--sources-dir", type=Path, default=Path("output") / "sources")
    parser.add_argument("--logs-dir", type=Path, default=Path("output") / "logs")
    parser.add_argument("--amass-json", type=Path, action="append", help="Optional staged Amass result JSON.")
    parser.add_argument("--literature-json", type=Path, action="append", help="Optional pre-collected open-literature JSON.")
    parser.add_argument("--skip-open-literature", action="store_true", help="Use only provided secondary branch JSON.")
    parser.add_argument("--no-validate", action="store_true", help="Skip schema validation in generation/fill stages.")
    parser.add_argument("--dry-run", action="store_true", help="Parse input and show decomposition summaries without network calls.")
    parser.add_argument("--report-path", type=Path, help="Pipeline run report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_id = safe_run_id()
    input_path = materialize_input(args, run_id)

    exercises = load_exercises(input_path)
    if not exercises:
        parser.error(f"No exercises found in input: {input_path}")

    if args.dry_run:
        report = build_dry_run_report(input_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    logs_dir = resolve_project_path(args.logs_dir)
    literature_jsons = list(args.literature_json or [])
    command_logs: list[dict[str, Any]] = []

    if not literature_jsons and not args.skip_open_literature:
        open_literature_output = logs_dir / f"{run_id}.open_literature_results.json"
        command_logs.append(
            run_command(
                [
                    sys.executable,
                    "pipeline/open_literature.py",
                    str(input_path),
                    "--retmax",
                    str(args.retmax),
                    "--output",
                    str(open_literature_output),
                ]
            )
        )
        literature_jsons.append(open_literature_output)

    generate_report_path = logs_dir / f"{run_id}.generate_cards_report.json"
    generate_command = [
        sys.executable,
        "pipeline/generate_cards.py",
        str(input_path),
        "--retmax",
        str(args.retmax),
        "--cards-dir",
        str(args.cards_dir),
        "--sources-dir",
        str(args.sources_dir),
        "--logs-dir",
        str(args.logs_dir),
        "--report-path",
        str(generate_report_path),
    ]
    for path in args.amass_json or []:
        generate_command.extend(["--amass-json", str(path)])
    for path in literature_jsons:
        generate_command.extend(["--literature-json", str(path)])
    if args.no_validate:
        generate_command.append("--no-validate")
    command_logs.append(run_command(generate_command))

    populate_logs = []
    for entry in exercises:
        populate_command = [sys.executable, "pipeline/populate_card.py", "--exercise-id", entry.exercise_id]
        if args.no_validate:
            populate_command.append("--no-validate")
        populate_log = run_command(populate_command)
        command_logs.append(populate_log)
        populate_logs.append(
            {
                "exercise_id": entry.exercise_id,
                "card_path": str(resolve_project_path(args.cards_dir) / f"{entry.exercise_id}.json"),
            }
        )

    report = {
        "generated_at": now_iso(),
        "run_id": run_id,
        "input_file": str(input_path),
        "exercise_count": len(exercises),
        "exercise_ids": [entry.exercise_id for entry in exercises],
        "open_literature_json": [str(path) for path in literature_jsons],
        "generate_report_path": str(generate_report_path),
        "populated_cards": populate_logs,
        "commands": command_logs,
    }
    report_path = resolve_project_path(args.report_path) if args.report_path else logs_dir / f"{run_id}.run_generation_report.json"
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
