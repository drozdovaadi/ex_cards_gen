#!/usr/bin/env python
"""
Build an exercise movement decomposition from the input text itself.

The module is deliberately component-based: it inspects the supplied exercise
name, aliases, and notes, then returns movement components, search aliases, and
evidence tiers. It is not keyed by exercise id and does not select a preset
exercise card.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]


TIER_ORDER = ["specific_variation", "exercise_family", "movement_pattern"]


@dataclass(frozen=True)
class MovementComponent:
    component_id: str
    label_ru: str
    description_ru: str
    taxonomy_pattern_id: str | None
    freeform_pattern_ru: str | None
    query_terms: list[str]
    evidence_tier: str
    rationale: str


@dataclass(frozen=True)
class MovementDecomposition:
    exercise_id: str
    raw_name: str
    exercise_name: str
    russian_name: str
    aliases: list[str] = field(default_factory=list)
    notes: str = ""
    components: list[MovementComponent] = field(default_factory=list)
    query_aliases: dict[str, list[str]] = field(default_factory=dict)
    taxonomy_patterns: list[str] = field(default_factory=list)
    unmapped_components: list[dict[str, str]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_key(value: Any) -> str:
    value = normalize_space(value).lower()
    value = value.replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return normalize_space(value)


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_space(value)
        key = normalize_key(normalized)
        if normalized and key and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def entry_value(entry: Any, key: str, default: Any = "") -> Any:
    if isinstance(entry, Mapping):
        return entry.get(key, default)
    return getattr(entry, key, default)


def entry_text(entry: Any) -> str:
    parts = [
        entry_value(entry, "raw_name"),
        entry_value(entry, "exercise_name"),
        entry_value(entry, "russian_name"),
        " ".join(entry_value(entry, "aliases", []) or []),
        entry_value(entry, "notes"),
    ]
    return normalize_key(" ".join(str(part or "") for part in parts))


def contains_any(text: str, *needles: str) -> bool:
    return any(normalize_key(needle) in text for needle in needles)


def contains_all(text: str, *needles: str) -> bool:
    return all(normalize_key(needle) in text for needle in needles)


def component(
    component_id: str,
    label_ru: str,
    description_ru: str,
    taxonomy_pattern_id: str | None,
    query_terms: list[str],
    *,
    evidence_tier: str = "exercise_family",
    freeform_pattern_ru: str | None = None,
    rationale: str,
) -> MovementComponent:
    return MovementComponent(
        component_id=component_id,
        label_ru=label_ru,
        description_ru=description_ru,
        taxonomy_pattern_id=taxonomy_pattern_id,
        freeform_pattern_ru=freeform_pattern_ru,
        query_terms=unique_strings(query_terms),
        evidence_tier=evidence_tier,
        rationale=rationale,
    )


def detect_components(text: str) -> list[MovementComponent]:
    components: list[MovementComponent] = []

    def add(candidate: MovementComponent) -> None:
        if candidate.component_id not in {item.component_id for item in components}:
            components.append(candidate)

    if contains_any(text, "single leg", "single-leg", "one leg", "одноопор", "одной ног", "unilateral"):
        add(
            component(
                "unilateral_support",
                "Одноопорная работа",
                "Упражнение требует удерживать центр масс над одной опорной ногой или выраженно асимметричной опорой.",
                None,
                ["single-leg exercise", "unilateral resistance exercise", "single-leg balance"],
                evidence_tier="movement_pattern",
                freeform_pattern_ru="одноопорный контроль равновесия",
                rationale="Распознаны слова, указывающие на одноопорную или асимметричную стойку.",
            )
        )

    if contains_any(text, "rdl", "romanian", "deadlift", "hinge", "журавлик", "румын", "станов", "наклон через таз"):
        terms = ["Romanian deadlift", "single-leg Romanian deadlift", "single-leg RDL", "hip hinge exercise"]
        if contains_any(text, "single leg", "single-leg", "одноопор", "одной ног", "журавлик"):
            terms.insert(0, "single-leg Romanian deadlift")
        add(
            component(
                "hip_hinge",
                "Наклон через тазобедренный сустав",
                "Основная часть движения включает сгибание и разгибание в тазобедренном суставе при сохранении контролируемого положения корпуса.",
                "hinge",
                terms,
                rationale="Распознаны признаки варианта румынской тяги, становой тяги или тазобедренного наклона.",
            )
        )

    if contains_any(text, "hip airplane", "open hip", "airplane", "раскрыт", "раскрытие таза", "ротац"):
        add(
            component(
                "open_hip_rotation",
                "Раскрытие таза и внешняя ротация бедра",
                "Свободная нога и таз поворачиваются наружу, а опорная сторона удерживает контроль таза во фронтальной и поперечной плоскостях.",
                "hip_abduction",
                ["hip airplane", "hip external rotation exercise", "hip abductor exercise", "frontal plane hip control"],
                freeform_pattern_ru="раскрытие таза с активной внешней ротацией бедра",
                rationale="Распознаны признаки hip airplane, раскрытия таза или ротационного компонента бедра.",
            )
        )
        add(
            component(
                "trunk_pelvis_rotation_control",
                "Контроль ротации корпуса и таза",
                "Поворот таза требует удерживать корпус без потери положения позвоночника и контролировать вращение вокруг опорного бедра.",
                "anti_rotation",
                ["trunk rotation control", "lumbopelvic stability", "anti-rotation exercise"],
                evidence_tier="movement_pattern",
                rationale="Ротация таза добавляет компонент контроля вращения корпуса относительно опорной ноги.",
            )
        )

    if contains_any(text, "woodchopper", "wood chopper", "chop", "cable chop", "дровосек", "диагонал"):
        add(
            component(
                "diagonal_trunk_rotation",
                "Диагональная ротация корпуса",
                "Движение строится вокруг диагональной линии тяги и поворота корпуса с контролем таза и грудного отдела.",
                "trunk_rotation",
                ["cable woodchopper", "cable chop", "diagonal trunk rotation", "medicine ball wood chop"],
                rationale="Распознаны признаки woodchopper/chop или диагонального ротационного движения.",
            )
        )

    if contains_any(text, "row", "тяга в наклоне", "тяга сидя", "греб", "горизонтальная тяга"):
        add(
            component(
                "horizontal_pull",
                "Горизонтальная тяга",
                "Плечо движется назад относительно корпуса, а лопатка выполняет приведение и контроль положения грудного отдела.",
                "horizontal_pull",
                ["row", "seated cable row", "bent-over row", "horizontal pull exercise"],
                rationale="Распознаны row/тяга с горизонтальным направлением усилия.",
            )
        )

    if contains_any(text, "pull-up", "pull up", "chin-up", "chin up", "pulldown", "подтяг", "верхняя тяга", "тяга сверху"):
        add(
            component(
                "vertical_pull",
                "Вертикальная тяга",
                "Плечо приводится и разгибается из поднятого положения, а лопатка опускается и стабилизируется.",
                "vertical_pull",
                ["pull-up", "chin-up", "lat pulldown", "vertical pull exercise"],
                rationale="Распознаны подтягивание, chin-up или верхняя тяга.",
            )
        )

    if contains_any(text, "pullover", "straight arm pulldown", "straight-arm pulldown", "пуловер", "тяга прямыми руками"):
        add(
            component(
                "shoulder_extension_pull",
                "Разгибание плеча с почти прямой рукой",
                "Плечо разгибается или приводится вниз без выраженного сгибания локтя, поэтому нагрузка смещается к широчайшим и большой круглой.",
                "shoulder_extension",
                ["dumbbell pullover", "machine pullover", "straight-arm pulldown", "shoulder extension exercise"],
                rationale="Распознаны pullover или тяга прямыми руками.",
            )
        )

    if contains_any(text, "squat", "присед"):
        add(
            component(
                "squat",
                "Приседательное движение",
                "Колено и тазобедренный сустав одновременно сгибаются и разгибаются, а корпус удерживает внешнюю нагрузку.",
                "squat",
                ["squat", "barbell squat", "resistance training squat"],
                rationale="Распознаны признаки приседа.",
            )
        )

    if contains_any(text, "split squat", "bulgarian", "lunge", "выпад", "сплит"):
        add(
            component(
                "lunge_split_squat",
                "Выпад или сплит-присед",
                "Асимметричная стойка повышает требование к тазу, колену и стабилизации корпуса.",
                "split_squat",
                ["split squat", "Bulgarian split squat", "lunge", "unilateral squat"],
                rationale="Распознаны признаки выпада или сплит-приседа.",
            )
        )

    if contains_any(text, "leg press", "жим ногами"):
        add(
            component(
                "leg_press",
                "Жим ногами",
                "Нижняя конечность разгибает колено и тазобедренный сустав при внешней опоре корпуса.",
                "squat",
                ["leg press", "sled leg press", "45 degree leg press"],
                rationale="Распознаны признаки жима ногами.",
            )
        )

    if contains_any(text, "leg extension", "разгибание ног", "разгибания ног"):
        add(
            component(
                "knee_extension",
                "Изолированное разгибание колена",
                "Основное движение происходит в коленном суставе с акцентом на четырехглавую мышцу бедра.",
                "knee_extension",
                ["leg extension", "knee extension exercise"],
                rationale="Распознаны признаки разгибания колена.",
            )
        )

    if contains_any(text, "leg curl", "hamstring curl", "сгибание ног", "сгибания ног"):
        add(
            component(
                "knee_flexion",
                "Сгибание колена",
                "Сопротивление создается против сгибания колена с акцентом на заднюю поверхность бедра.",
                "knee_flexion",
                ["leg curl", "hamstring curl", "knee flexion exercise"],
                rationale="Распознаны признаки сгибания колена.",
            )
        )

    if contains_any(text, "hip thrust", "glute bridge", "ягодичный мост", "хип траст"):
        add(
            component(
                "hip_thrust_bridge",
                "Разгибание бедра с опорой корпуса",
                "Таз разгибается из согнутого положения, а нагрузка обычно пиково ощущается ближе к верхней позиции.",
                "hip_thrust_bridge",
                ["hip thrust", "glute bridge", "hip extension exercise"],
                rationale="Распознаны признаки hip thrust или ягодичного моста.",
            )
        )

    if contains_any(text, "kickback", "отведение ноги назад"):
        add(
            component(
                "hip_extension_isolation",
                "Изолированное разгибание бедра",
                "Бедро уходит назад против внешнего сопротивления при ограниченном движении колена.",
                "hinge",
                ["glute kickback", "hip extension exercise", "cable hip extension"],
                rationale="Распознаны признаки kickback или отведения ноги назад.",
            )
        )

    if contains_any(text, "hip abduction", "abductor", "отведение бедра", "отведения бедра"):
        add(
            component(
                "hip_abduction",
                "Отведение бедра",
                "Бедро уходит в сторону, а средняя ягодичная и соседние мышцы контролируют фронтальную плоскость.",
                "hip_abduction",
                ["hip abduction", "hip abductor exercise"],
                rationale="Распознаны признаки отведения бедра.",
            )
        )

    if contains_any(text, "hip adduction", "adductor", "приведение бедра", "приведения бедра"):
        add(
            component(
                "hip_adduction",
                "Приведение бедра",
                "Бедро движется к средней линии против сопротивления с акцентом на приводящие мышцы.",
                "hip_adduction",
                ["hip adduction", "hip adductor exercise"],
                rationale="Распознаны признаки приведения бедра.",
            )
        )

    if contains_any(text, "calf raise", "икры", "подъем на носки", "подъём на носки"):
        add(
            component(
                "plantar_flexion",
                "Подошвенное сгибание стопы",
                "Основное движение происходит в голеностопном суставе против внешней нагрузки.",
                "plantar_flexion",
                ["calf raise", "ankle plantar flexion exercise"],
                rationale="Распознаны признаки подъема на носки.",
            )
        )

    if contains_any(text, "bench press", "push-up", "push up", "жим лежа", "жим лёжа", "отжим"):
        add(
            component(
                "horizontal_push",
                "Горизонтальное жимовое движение",
                "Плечо выполняет горизонтальное приведение или сгибание, локоть разгибается против сопротивления.",
                "horizontal_push",
                ["bench press", "push-up", "horizontal press exercise"],
                rationale="Распознаны признаки горизонтального жима.",
            )
        )

    if contains_any(text, "shoulder press", "overhead press", "military press", "жим над головой", "армейский жим"):
        add(
            component(
                "vertical_push",
                "Вертикальное жимовое движение",
                "Нагрузка перемещается над головой через сгибание или отведение плеча и разгибание локтя.",
                "vertical_push",
                ["overhead press", "shoulder press", "vertical press exercise"],
                rationale="Распознаны признаки вертикального жима.",
            )
        )

    if contains_any(text, "lateral raise", "мах в сторону", "подъем через стороны", "подъём через стороны"):
        add(
            component(
                "shoulder_abduction",
                "Отведение плеча",
                "Плечо поднимается в сторону против сопротивления с акцентом на среднюю дельтовидную.",
                "shoulder_abduction",
                ["lateral raise", "shoulder abduction exercise"],
                rationale="Распознаны признаки подъема плеча через сторону.",
            )
        )

    if contains_any(text, "rear delt", "reverse fly", "обратная разводка", "задняя дельта"):
        add(
            component(
                "shoulder_horizontal_abduction",
                "Горизонтальное отведение плеча",
                "Плечи разводятся назад, лопатки стабилизируются, а задняя дельтовидная работает как главный двигатель.",
                None,
                ["reverse fly", "rear delt fly", "shoulder horizontal abduction"],
                freeform_pattern_ru="горизонтальное отведение плеча",
                rationale="Распознаны признаки reverse fly или работы на заднюю дельтовидную.",
            )
        )

    if contains_any(text, "curl", "сгибание рук", "подъем на бицепс", "подъём на бицепс"):
        add(
            component(
                "elbow_flexion",
                "Сгибание локтя",
                "Основное движение происходит в локтевом суставе с акцентом на сгибатели локтя.",
                "elbow_flexion",
                ["biceps curl", "elbow flexion exercise"],
                rationale="Распознаны признаки сгибания локтя.",
            )
        )

    if contains_any(text, "pushdown", "triceps extension", "французский жим", "разгибание рук", "трицепс"):
        add(
            component(
                "elbow_extension",
                "Разгибание локтя",
                "Основное движение происходит в локтевом суставе с акцентом на трехглавую мышцу плеча.",
                "elbow_extension",
                ["triceps extension", "triceps pushdown", "elbow extension exercise"],
                rationale="Распознаны признаки разгибания локтя.",
            )
        )

    if contains_any(text, "plank", "планка"):
        add(
            component(
                "core_anti_extension",
                "Удержание корпуса от разгибания",
                "Корпус удерживается без провисания поясницы, сопротивляясь разгибанию позвоночника.",
                "anti_extension",
                ["plank", "anti-extension exercise", "core stabilization"],
                evidence_tier="movement_pattern",
                rationale="Распознаны признаки планки.",
            )
        )

    if contains_any(text, "crunch", "скручив"):
        add(
            component(
                "trunk_flexion",
                "Сгибание корпуса",
                "Позвоночник сгибается против сопротивления или веса тела.",
                "trunk_flexion",
                ["crunch", "trunk flexion exercise", "abdominal exercise"],
                rationale="Распознаны признаки скручивания.",
            )
        )

    return components


def default_generic_component() -> MovementComponent:
    return component(
        "unmapped_resistance_exercise",
        "Неуточненный силовой паттерн",
        "По названию не удалось надежно выделить отдельный таксономический паттерн; дальнейшее заполнение должно опираться на найденные источники и явно помеченные аналитические допущения.",
        None,
        ["resistance exercise biomechanics", "strength exercise technique", "exercise biomechanics"],
        evidence_tier="movement_pattern",
        freeform_pattern_ru="неуточненное силовое движение",
        rationale="Название и alias не содержат достаточных признаков для надежного разложения на известные компоненты.",
    )


def build_query_aliases(entry: Any, components: list[MovementComponent]) -> dict[str, list[str]]:
    raw_name = normalize_space(entry_value(entry, "raw_name"))
    exercise_name = normalize_space(entry_value(entry, "exercise_name"))
    aliases = entry_value(entry, "aliases", []) or []
    exact = unique_strings([raw_name, exercise_name, *aliases])

    family_terms: list[str] = []
    pattern_terms: list[str] = []
    for item in components:
        if item.evidence_tier == "movement_pattern":
            pattern_terms.extend(item.query_terms)
        else:
            family_terms.extend(item.query_terms)
            if item.taxonomy_pattern_id:
                pattern_terms.append(item.taxonomy_pattern_id.replace("_", " "))
            pattern_terms.extend(item.query_terms[-1:])

    return {
        "specific_variation": exact,
        "exercise_family": unique_strings(family_terms),
        "movement_pattern": unique_strings(pattern_terms),
    }


def build_movement_decomposition(entry: Any) -> MovementDecomposition:
    text = entry_text(entry)
    components = detect_components(text)
    limitations: list[str] = []
    if not components:
        components = [default_generic_component()]
        limitations.append(
            "Прямое распознавание паттерна по названию и alias не удалось; компонент создан как общий movement-pattern уровень."
        )

    component_ids = {component.component_id for component in components}
    taxonomy_pattern_candidates = [
        component.taxonomy_pattern_id for component in components if component.taxonomy_pattern_id
    ]
    if "trunk_pelvis_rotation_control" in component_ids:
        taxonomy_pattern_candidates.append("trunk_rotation")
    taxonomy_patterns = unique_strings(taxonomy_pattern_candidates)
    if not taxonomy_patterns:
        taxonomy_patterns = ["unclear"]
    unmapped_components = [
        {
            "component_id": component.component_id,
            "freeform_pattern_ru": component.freeform_pattern_ru or component.label_ru,
            "reason": "Компонент не имеет прямого enum-значения в текущей taxonomy.",
        }
        for component in components
        if component.taxonomy_pattern_id is None or component.freeform_pattern_ru
    ]
    confidence = "medium" if components and components[0].component_id != "unmapped_resistance_exercise" else "low"

    return MovementDecomposition(
        exercise_id=normalize_space(entry_value(entry, "exercise_id")) or "unknown_exercise",
        raw_name=normalize_space(entry_value(entry, "raw_name")),
        exercise_name=normalize_space(entry_value(entry, "exercise_name")),
        russian_name=normalize_space(entry_value(entry, "russian_name")),
        aliases=unique_strings(entry_value(entry, "aliases", []) or []),
        notes=normalize_space(entry_value(entry, "notes")),
        components=components,
        query_aliases=build_query_aliases(entry, components),
        taxonomy_patterns=taxonomy_patterns,
        unmapped_components=unmapped_components,
        limitations=limitations,
        confidence=confidence,
    )


def decomposition_summary(decomposition: MovementDecomposition | dict[str, Any]) -> dict[str, Any]:
    data = decomposition.to_dict() if isinstance(decomposition, MovementDecomposition) else decomposition
    components = data.get("components") or []
    return {
        "component_ids": [item.get("component_id") for item in components if isinstance(item, dict)],
        "taxonomy_patterns": data.get("taxonomy_patterns") or [],
        "unmapped_component_ids": [
            item.get("component_id") for item in data.get("unmapped_components") or [] if isinstance(item, dict)
        ],
        "query_alias_counts": {
            scope: len(aliases or []) for scope, aliases in (data.get("query_aliases") or {}).items()
        },
        "confidence": data.get("confidence"),
        "limitations": data.get("limitations") or [],
    }


def load_decomposition(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_decomposition(path: Path, decomposition: MovementDecomposition | dict[str, Any]) -> None:
    data = decomposition.to_dict() if isinstance(decomposition, MovementDecomposition) else decomposition
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build movement decomposition for a single exercise text.")
    parser.add_argument("exercise", help="Exercise name as supplied by the user or input file.")
    parser.add_argument("--alias", action="append", default=[], help="Optional alias. Can be passed multiple times.")
    parser.add_argument("--notes", default="", help="Optional technique notes.")
    parser.add_argument("--exercise-id", default="", help="Optional exercise id.")
    parser.add_argument("--output", type=Path, help="Optional output JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    entry = {
        "raw_name": args.exercise,
        "russian_name": args.exercise,
        "exercise_name": next((alias for alias in args.alias if re.search(r"[A-Za-z]", alias)), args.exercise),
        "exercise_id": args.exercise_id or normalize_key(args.exercise).replace(" ", "_") or "exercise",
        "aliases": args.alias,
        "notes": args.notes,
    }
    decomposition = build_movement_decomposition(entry)
    data = decomposition.to_dict()
    if args.output:
        output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        save_decomposition(output, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
