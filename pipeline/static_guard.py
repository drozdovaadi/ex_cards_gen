#!/usr/bin/env python
"""Static checks for production pipeline code."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TOKENS = ("PRO" + "FILES", "BUILD" + "ERS")


def scan_pipeline(root: Path) -> list[tuple[Path, int, str, str]]:
    findings: list[tuple[Path, int, str, str]] = []
    for path in sorted((root / "pipeline").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for token in FORBIDDEN_TOKENS:
                if token in line:
                    findings.append((path, line_no, token, line.strip()))
    return findings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run static production guards.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="Project root.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
    findings = scan_pipeline(root)
    if findings:
        for path, line_no, token, line in findings:
            rel = path.relative_to(root)
            print(f"{rel}:{line_no}: forbidden token {token}: {line}", file=sys.stderr)
        return 1
    print("static_guard: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
