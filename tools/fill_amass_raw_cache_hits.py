#!/usr/bin/env python
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "output" / "logs" / "amass_query_plan.json"
RAW_DIR = ROOT / "output" / "logs" / "amass_raw"


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8-sig"))
    groups: dict[tuple[str, bool, int], list[tuple[str, str, Path, bool]]] = defaultdict(list)

    for exercise in plan.get("exercises", []):
        exercise_id = exercise["exercise_id"]
        for query in exercise.get("queries", []):
            params = query.get("parameters") or {}
            key = (
                params.get("query") or "",
                bool(params.get("isRetracted")),
                int(params.get("minJournalQualityJufo") or 0),
            )
            path = RAW_DIR / exercise_id / f"{query['query_id']}.json"
            groups[key].append((exercise_id, query["query_id"], path, path.exists()))

    filled = []
    for items in groups.values():
        source = next((path for _exercise_id, _query_id, path, exists in items if exists), None)
        if source is None:
            continue
        for exercise_id, query_id, path, exists in items:
            if exists:
                continue
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "pipeline" / "amass_raw.py"),
                    "save",
                    "--force",
                    "--exercise-id",
                    exercise_id,
                    "--query-id",
                    query_id,
                    "--payload-file",
                    str(source),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            filled.append({"exercise_id": exercise_id, "query_id": query_id, "source": str(source)})

    print(json.dumps({"filled_count": len(filled), "filled": filled}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
