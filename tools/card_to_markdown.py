#!/usr/bin/env python
"""Render exercise card JSON files into human-readable Markdown tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARDS_DIR = PROJECT_ROOT / "output" / "exercise_cards"


PASSPORT_KEYS = [
    "id",
    "type",
    "status",
    "schema_version",
    "language",
    "names",
    "exercise_name",
    "russian_name",
    "exercise_id",
    "aliases",
]

CLASSIFICATION_KEYS = [
    "exercise_family",
    "variation",
    "variation_of",
    "related_variations",
    "category",
    "body_region",
    "target_region",
    "dominance_type",
    "display_labels",
    "modality",
    "equipment_required",
    "compound_type",
    "movement_patterns",
    "force_vector",
    "kinetic_chain",
    "movement_planes",
    "body_position",
    "limb_pattern",
    "technical_complexity",
]

TOP_LEVEL_GROUPS = [
    (
        "Требования и паттерн движения",
        [
            "mobility_requirements",
            "movement_pattern_details",
        ],
    ),
    (
        "Мышцы",
        [
            "primary_muscles",
            "secondary_muscles",
            "stabilizers",
        ],
    ),
    (
        "Фазовый акцент и профиль нагрузки",
        [
            "joint_actions",
            "contraction_phase_emphasis",
            "stimulus_phase_bias",
            "muscle_stimulus_phase_bias",
            "resistance_profile",
            "relative_muscle_emphasis",
            "fatigue_cost",
            "sfr",
        ],
    ),
    (
        "Ошибки, ограничения техники и программирование",
        [
            "common_errors",
            "typical_rep_ranges",
            "progression_options",
            "when_to_avoid_or_modify",
            "prerequisite_skill_mobility",
            "variations",
            "alternatives",
            "safety",
        ],
    ),
    (
        "Ограничения и доказательность",
        [
            "assumptions",
            "limitations",
            "not_supported_claims",
            "evidence_summary",
            "evidence_ledger",
            "metadata",
        ],
    ),
]

FIELD_LABELS = {
    "dominance_label_ru": "Доминанта",
    "load_phase_label_ru": "Фаза нагрузки",
    "contraction_phase_label_ru": "Фазовый режим сокращения",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def markdown_escape(value: Any) -> str:
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", "<br>")
    return text


def is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def value_to_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if is_scalar(value):
        return markdown_escape(value)
    if isinstance(value, list):
        if not value:
            return "—"
        if all(is_scalar(item) for item in value):
            return "<br>".join(markdown_escape(item) for item in value)
        return "<br>".join(markdown_escape(json.dumps(item, ensure_ascii=False)) for item in value)
    if isinstance(value, dict):
        if not value:
            return "—"
        lines = []
        for key, item in value.items():
            label = FIELD_LABELS.get(key, key)
            lines.append(f"{markdown_escape(label)}: {value_to_cell(item)}")
        return "<br>".join(lines)
    return markdown_escape(value)


def flatten_for_kv(data: dict[str, Any], keys: list[str]) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key in keys:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, dict) and key in {"names", "display_labels"}:
            for child_key, child_value in value.items():
                label = FIELD_LABELS.get(child_key, f"{key}.{child_key}")
                rows.append((label, child_value))
        else:
            rows.append((key, value))
    return rows


def render_kv_table(title: str, rows: list[tuple[str, Any]], level: int = 2) -> list[str]:
    if not rows:
        return []
    lines = [f"{'#' * level} {title}", "", "| Поле | Значение |", "| --- | --- |"]
    for key, value in rows:
        lines.append(f"| {markdown_escape(key)} | {value_to_cell(value)} |")
    lines.append("")
    return lines


def table_columns(items: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for item in items:
        for key in item.keys():
            if key not in columns:
                columns.append(key)
    return columns


def render_list_table(title: str, items: list[Any], level: int = 3) -> list[str]:
    lines = [f"{'#' * level} {title}", ""]
    if not items:
        lines.extend(["| # | Значение |", "| --- | --- |", "| — | — |", ""])
        return lines
    if all(isinstance(item, dict) for item in items):
        dict_items = [item for item in items if isinstance(item, dict)]
        columns = table_columns(dict_items)
        lines.append("| " + " | ".join(markdown_escape(column) for column in columns) + " |")
        lines.append("| " + " | ".join("---" for _ in columns) + " |")
        for item in dict_items:
            lines.append("| " + " | ".join(value_to_cell(item.get(column)) for column in columns) + " |")
        lines.append("")
        return lines
    lines.extend(["| # | Значение |", "| --- | --- |"])
    for index, item in enumerate(items, start=1):
        lines.append(f"| {index} | {value_to_cell(item)} |")
    lines.append("")
    return lines


def render_value_section(title: str, value: Any, level: int = 3) -> list[str]:
    if isinstance(value, list):
        return render_list_table(title, value, level)
    if isinstance(value, dict):
        return render_dict_section(title, value, level)
    return render_kv_table(title, [("Значение", value)], level)


def render_dict_section(title: str, data: dict[str, Any], level: int = 3) -> list[str]:
    lines = [f"{'#' * level} {title}", ""]
    scalar_rows: list[tuple[str, Any]] = []
    nested: list[tuple[str, Any]] = []
    for key, value in data.items():
        if is_scalar(value) or (isinstance(value, list) and all(is_scalar(item) for item in value)):
            scalar_rows.append((key, value))
        else:
            nested.append((key, value))
    if scalar_rows:
        lines.extend(["| Поле | Значение |", "| --- | --- |"])
        for key, value in scalar_rows:
            lines.append(f"| {markdown_escape(key)} | {value_to_cell(value)} |")
        lines.append("")
    for key, value in nested:
        lines.extend(render_value_section(f"{title}.{key}", value, level + 1))
    if not scalar_rows and not nested:
        lines.extend(["| Поле | Значение |", "| --- | --- |", "| — | — |", ""])
    return lines


def render_best_use_section(best_use: Any) -> list[str]:
    if not isinstance(best_use, dict):
        return []
    lines = ["## Когда выбирать это упражнение", ""]
    summary = best_use.get("summary")
    if summary:
        lines.extend([markdown_escape(summary), ""])
    detail_rows = [(key, value) for key, value in best_use.items() if key != "summary"]
    if detail_rows:
        lines.extend(render_kv_table("Детали применения", detail_rows, level=3))
    return lines


def render_card(card: dict[str, Any], source_path: Path) -> str:
    title = card.get("russian_name") or (card.get("names") or {}).get("ru") or card.get("exercise_name") or card["id"]
    lines = [
        f"# {markdown_escape(title)}",
        "",
        f"Исходный файл: `{source_path}`",
        "",
    ]
    lines.extend(render_kv_table("Паспорт карточки", flatten_for_kv(card, PASSPORT_KEYS), level=2))
    lines.extend(render_kv_table("Классификация", flatten_for_kv(card, CLASSIFICATION_KEYS), level=2))

    for group_title, keys in TOP_LEVEL_GROUPS[:2]:
        lines.append(f"## {group_title}")
        lines.append("")
        for key in keys:
            if key in card:
                lines.extend(render_value_section(key, card[key], level=3))

    if "biomechanics" in card:
        lines.append("## Биомеханика")
        lines.append("")
        lines.extend(render_dict_section("biomechanics", card["biomechanics"], level=3))

    for group_title, keys in TOP_LEVEL_GROUPS[2:3]:
        lines.append(f"## {group_title}")
        lines.append("")
        for key in keys:
            if key in card:
                lines.extend(render_value_section(key, card[key], level=3))

    if "execution_steps" in card:
        lines.append("## Пошаговая техника выполнения")
        lines.append("")
        lines.extend(render_value_section("execution_steps", card["execution_steps"], level=3))

    for group_title, keys in TOP_LEVEL_GROUPS[3:4]:
        lines.append(f"## {group_title}")
        lines.append("")
        for key in keys:
            if key in card:
                lines.extend(render_value_section(key, card[key], level=3))

    if "supersets_trisets" in card:
        lines.append("## Суперсеты и трисеты")
        lines.append("")
        lines.extend(render_value_section("supersets_trisets", card["supersets_trisets"], level=3))

    for group_title, keys in TOP_LEVEL_GROUPS[4:]:
        lines.append(f"## {group_title}")
        lines.append("")
        for key in keys:
            if key in card:
                lines.extend(render_value_section(key, card[key], level=3))

    if "best_use" in card:
        lines.extend(render_best_use_section(card["best_use"]))

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_path(path: Path) -> Path:
    card = load_json(path)
    target = path.with_suffix(".md")
    target.write_text(render_card(card, path), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Render exercise card JSON files into Markdown.")
    parser.add_argument("--cards-dir", type=Path, default=DEFAULT_CARDS_DIR)
    parser.add_argument("--card", type=Path, help="Render one JSON card.")
    parser.add_argument("--all", action="store_true", help="Render every JSON card in --cards-dir.")
    args = parser.parse_args()

    if args.card:
        paths = [args.card]
    elif args.all:
        paths = sorted(args.cards_dir.glob("*.json"))
    else:
        parser.error("Use --card or --all.")

    rendered = [render_path(path) for path in paths]
    print(json.dumps({"rendered": [str(path) for path in rendered], "count": len(rendered)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
