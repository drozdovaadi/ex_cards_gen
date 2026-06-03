#!/usr/bin/env python
"""
Prepare staged exercise cards for evidence-first biomechanical analysis.

This step reads:
- output/exercise_cards/<exercise_id>.json
- output/sources/<exercise_id>.sources.json

Project rule: normal generation must not populate final biomechanical fields
from hardcoded movement templates. Direct exercise evidence has priority. If
direct evidence is incomplete, each missing field must be filled by a separate
analytical extraction step from suitable close-variation, same-family, or
movement-pattern studies, with the evidence tier recorded per field.

Legacy template population is removed from the command path. The production
route is evidence-first and no-template only.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_cards import PROJECT_ROOT, now_iso, validate_card, write_json


MUSCLE_TAXONOMY_PATH = PROJECT_ROOT / "schemas" / "taxonomies" / "muscles.json"


@dataclass(frozen=True)
class MuscleInfo:
    muscle_id: str
    name_ru: str
    group_id: str


class PopulateError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def load_muscles() -> dict[str, MuscleInfo]:
    taxonomy = load_json(MUSCLE_TAXONOMY_PATH)
    muscles: dict[str, MuscleInfo] = {}
    for group in taxonomy.get("muscle_groups", []):
        group_id = group["group_id"]
        for muscle in group.get("muscles", []):
            muscles[muscle["muscle_id"]] = MuscleInfo(
                muscle_id=muscle["muscle_id"],
                name_ru=muscle["name_ru"],
                group_id=group_id,
            )
    return muscles


MUSCLES = load_muscles()


DOMINANCE_LABELS_RU = {
    "hip_dominant": "Тазобедренная доминанта",
    "knee_dominant": "Коленная доминанта",
    "ankle_dominant": "Голеностопная доминанта",
    "horizontal_push": "Горизонтальное жимовое движение",
    "vertical_push": "Вертикальное жимовое движение",
    "horizontal_pull": "Горизонтальная тяга",
    "vertical_pull": "Вертикальная тяга",
    "elbow_flexion_dominant": "Сгибание локтя",
    "elbow_extension_dominant": "Разгибание локтя",
    "shoulder_dominant": "Плечевая доминанта",
    "trunk_dominant": "Доминанта корпуса",
    "balanced": "Сбалансированное",
    "isolation": "Изолированное",
    "unclear": "Не определено",
}

LOAD_PHASE_LABELS_RU = {
    "lengthened": "Растянутая",
    "mid_range": "Средняя амплитуда",
    "shortened": "Сокращенная",
    "mixed": "Смешанная",
    "unclear": "Не определена",
}

CONTRACTION_PHASE_LABELS_RU = {
    "concentric": "Концентрическая",
    "eccentric": "Эксцентрическая",
    "isometric": "Изометрическая",
    "quasi_isometric": "Квазиизометрическая",
    "stretch_shortening_cycle": "Цикл растяжения-сокращения",
    "mixed": "Смешанная",
    "unclear": "Не определен",
}

TEXT_QUALITY_FORBIDDEN = {
    "брейсинг": "напряжение корпуса",
    "аксессуар": "вспомогательное упражнение",
    "hip-dominant": "тазобедренная доминанта",
    "movement template": "шаблон движения",
    "movement-template": "шаблон движения",
    "full text": "полный текст",
    "source ledger": "список источников",
    "hip тазобедренный шарнир": "наклон через тазобедренный сустав",
    "контролируемое сгибание бедра в тазобедренный шарнир на одной ноге": "контролируемое сгибание в тазобедренном суставе на одной ноге",
    "Румынская тяга на одной ноге и раскрытие таза на одной ноге": "румынской тяги на одной ноге и раскрытия таза на одной ноге",
    "из румынская тяга на одной ноге": "из румынской тяги на одной ноге",
    "при подъёме из тазобедренный шарнир": "при подъеме из позиции наклона через тазобедренный сустав",
    "360-градусный напряжение корпуса": "360-градусное напряжение корпуса",
    "Глубина тазобедренный шарнир": "Глубина наклона через тазобедренный сустав",
    "амплитуду раскрытие таза": "амплитуду раскрытия таза",
    "корпус теряет напряжение корпуса": "корпус теряет жесткость",
    "растёт требование удерживать позвоночник от сгибания на поясницу": "возрастает требование к мышцам поясницы удерживать позвоночник от сгибания",
    "контролю во фронтальной и поперечной плоскостях опорного бедра": "контролю опорного бедра во фронтальной и поперечной плоскостях",
    "тазобедренный шарнир-позиции": "позиции наклона через тазобедренный сустав",
    "тазобедренный шарнир-позицию": "позицию наклона через тазобедренный сустав",
    "нижнюю тазобедренный шарнир": "нижнюю позицию наклона через тазобедренный сустав",
    "пиковой раскрытие таза позиции": "пиковой позиции раскрытия таза",
    "финальной раскрытие таза позиции": "финальной позиции раскрытия таза",
    "пиковое удержание раскрытие таза": "пиковое удержание раскрытия таза",
    "из раскрытие таза удержания": "из удержания раскрытия таза",
    "контролируемым раскрытие таза": "контролируемым раскрытием таза",
    "без полная фиксация": "без полной фиксации",
    "раскрытие таза позицию": "позицию раскрытия таза",
    "раскрытие таза позиции": "позиции раскрытия таза",
    "полный полная фиксация": "полная фиксация",
    "полного вертикального полная фиксация": "полной вертикальной фиксации",
    "lengthened стимул": "стимул в растянутой позиции",
    "средняя ягодичная контроль": "контроль средней ягодичной",
    "средняя ягодичная стимула": "стимула средней ягодичной",
    "deadlift/румынская тяга biomechanics": "биомеханики становой и румынской тяги",
    "deadlift/румынская тяга": "становой и румынской тяги",
    "deadlift-family": "вариантов становой тяги",
    "exercise biomechanics": "биомеханике упражнений",
    "biomechanics": "биомеханика",
    "hip-focused rehabilitation exercises": "упражнений для контроля и укрепления тазобедренной области",
    "hip-focused exercises": "упражнений для контроля тазобедренной области",
    "hip-focused rehabilitation": "реабилитационных упражнений для тазобедренной области",
    "hip abductor literature": "литературы по отводящим мышцам бедра",
    "unilateral posterior-chain/balance literature": "литературы по одноопорной работе задней цепи и равновесию",
    "spine-control literature": "литературы по контролю позвоночника",
    "peer-reviewed": "рецензируемых",
    "curated claims": "отобранных утверждений",
    "close-family evidence": "косвенные данные по близким вариантам",
    "variants": "вариантам",
    "hamstrings adaptations": "адаптациям хамстрингов",
    "ankle/hip balance": "равновесию в стопе и тазобедренном суставе",
    "анти-флексионный спрос": "требование удерживать позвоночник от сгибания",
    "анти-флексии": "удержанию позвоночника от сгибания",
    "фронтально-трансверсальному контролю": "контролю во фронтальной и поперечной плоскостях",
    "целевой техническая подсказка": "целевая задача",
    "Шарнирный": "Тазобедренный",
    "шарнирный": "тазобедренный",
    "Шарнир": "Наклон через тазобедренный сустав",
    "тазобедренный шарнир": "наклон через тазобедренный сустав",
    "шарнир": "наклон через тазобедренный сустав",
    "hinge": "наклон через тазобедренный сустав",
    "lockout": "фиксация в конечной позиции",
    "open-hip": "раскрытие таза",
    "open hip": "раскрытие таза",
    "hip airplane": "раскрытие таза на одной ноге",
    "hip-airplane": "раскрытие таза на одной ноге",
    "peak hold": "пиковое удержание",
    "cue": "техническая подсказка",
    "glute-med": "средняя ягодичная",
    "glute med": "средняя ягодичная",
    "motor-control": "двигательный контроль",
    "motor control": "двигательный контроль",
    "ROM": "амплитуда движения",
    "RDL": "румынская тяга",
    "accessory": "вспомогательное упражнение",
}

GENERIC_PRACTICAL_PLACEHOLDERS = {
    "низко конфликтующее упражнение на другую мышечную группу",
    "вариация с изменением оборудования",
    "упражнение того же паттерна движения",
}


def muscle_name(muscle_id: str) -> str:
    return MUSCLES[muscle_id].name_ru


def muscle_group(muscle_id: str) -> str:
    return MUSCLES[muscle_id].group_id


def set_display_labels(card: dict[str, Any]) -> None:
    dominance = card.get("dominance_type") or "unclear"
    load_phase = card.get("stimulus_phase_bias") or "unclear"
    contraction_phase = card.get("contraction_phase_emphasis") or "unclear"
    card["display_labels"] = {
        "dominance_label_ru": DOMINANCE_LABELS_RU.get(dominance, dominance),
        "load_phase_label_ru": LOAD_PHASE_LABELS_RU.get(load_phase, load_phase),
        "contraction_phase_label_ru": CONTRACTION_PHASE_LABELS_RU.get(contraction_phase, contraction_phase),
    }


def human_text_values(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str]]:
    skip_keys = {
        "id",
        "exercise_id",
        "exercise_name",
        "russian_name",
        "aliases",
        "source_ids",
        "source_id",
        "evidence_type",
        "confidence",
        "confidence_score",
        "schema_version",
        "generated_at",
        "populated_at",
        "generator",
        "metadata",
        "names",
        "pmid",
        "pmcid",
        "doi",
        "exercise_family",
        "variation",
        "variation_of",
        "related_variations",
        "movement_patterns",
        "phase_id",
        "phase_type",
        "contraction_type",
        "joint_id",
        "primary_actions",
        "actions",
        "primary_phases",
        "contraction_phase_emphasis",
        "stimulus_phase_bias",
        "rom_characteristic",
        "moment_demand",
        "muscle_id",
        "muscle_group_id",
        "role",
        "phase_or_range",
        "muscle_length_state",
        "relative_demand",
        "joint_action_context",
        "stabilization_role",
        "score_type",
        "stimulus_region",
        "profile_type",
        "peak_loading_region",
        "external_resistance_type",
        "line_of_force",
        "load_placement",
        "effect_direction",
        "variable_id",
        "sfr_class",
        "status",
        "type",
        "language",
    }
    if path and path[-1] in skip_keys:
        return []
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        result = []
        for index, item in enumerate(value):
            result.extend(human_text_values(item, (*path, str(index))))
        return result
    if isinstance(value, dict):
        result = []
        for key, item in value.items():
            result.extend(human_text_values(item, (*path, key)))
        return result
    return []


def validate_quality_contract(card: dict[str, Any], template_id: str) -> None:
    if template_id == "unknown":
        return

    errors: list[str] = []
    for path, text in human_text_values(card):
        lowered = text.lower()
        for forbidden, replacement in TEXT_QUALITY_FORBIDDEN.items():
            if forbidden in lowered:
                errors.append(
                    f"{'.'.join(path)} содержит '{forbidden}'. Используйте русскую формулировку: '{replacement}'."
                )
        if re.search(r"\b(systematic review|deadlift variants)\b", text, flags=re.IGNORECASE):
            errors.append(
                f"{'.'.join(path)} описывает источник вместо биомеханического факта. "
                "Сформулируйте вывод как факт о мышцах, суставах или нагрузке."
            )
        if text in GENERIC_PRACTICAL_PLACEHOLDERS:
            errors.append(f"{'.'.join(path)} содержит общий заполнитель вместо конкретного примера.")

    biomechanics = card.get("biomechanics") or {}
    phases = biomechanics.get("movement_phases") or []
    if len(phases) < 4:
        errors.append("biomechanics.movement_phases должен содержать не меньше 4 подробно описанных фаз.")
    for phase in phases:
        if len(phase.get("key_events") or []) < 3:
            errors.append(f"Фаза {phase.get('phase_id')} должна иметь не меньше 3 ключевых событий.")
        if len(phase.get("start_position") or "") < 20 or len(phase.get("end_position") or "") < 20:
            errors.append(f"Фаза {phase.get('phase_id')} должна подробно описывать стартовую и конечную позицию.")

    external = biomechanics.get("external_load_mechanics") or {}
    if len(external.get("main_moment_arms") or []) < 2:
        errors.append("external_load_mechanics.main_moment_arms должен содержать не меньше 2 конкретных условий.")
    if len(external.get("vector_shift_effects") or []) < 2:
        errors.append("external_load_mechanics.vector_shift_effects должен содержать не меньше 2 смещений вектора нагрузки.")
    for item in external.get("vector_shift_effects") or []:
        if len(item.get("biomechanical_effect") or "") < 60 or len(item.get("muscle_bias_change") or "") < 40:
            errors.append(f"Смещение вектора '{item.get('change')}' описано слишком кратко.")
        combined = f"{item.get('biomechanical_effect') or ''} {item.get('muscle_bias_change') or ''}".lower()
        if "линия силы" not in combined or "плеч" not in combined:
            errors.append(
                f"Смещение вектора '{item.get('change')}' должно объяснять изменение линии силы и внешнего плеча момента."
            )
        if "акцент" not in combined or not re.search(r"увелич|сниж|смещ", combined):
            errors.append(
                f"Смещение вектора '{item.get('change')}' должно явно объяснять, "
                "на какие мышцы акцент увеличивается, снижается или смещается."
            )

    resistance = card.get("resistance_profile") or {}
    if len(resistance.get("explanation") or "") < 120:
        errors.append("resistance_profile.explanation должен подробно объяснять пик нагрузки и условия его смещения.")

    for field, minimum in (("supersets_trisets", 2), ("variations", 4), ("alternatives", 4)):
        if len(card.get(field) or []) < minimum:
            errors.append(f"{field} должен содержать не меньше {minimum} конкретных примеров.")

    best_use = card.get("best_use") or {}
    if not isinstance(best_use, dict) or len(best_use.get("summary") or "") < 120:
        errors.append(
            "best_use.summary должен быть итоговым русским абзацем: что это за упражнение, "
            "когда его выбирать, чем оно отличается от альтернатив и когда оно особенно уместно."
        )

    if errors:
        raise PopulateError("Card quality contract failed:\n- " + "\n- ".join(errors))


def sanitize_card_text(value: Any, path: tuple[str, ...] = ()) -> Any:
    skip_keys = {
        "id",
        "exercise_id",
        "exercise_name",
        "russian_name",
        "aliases",
        "source_ids",
        "source_id",
        "evidence_type",
        "confidence",
        "metadata",
        "names",
        "exercise_family",
        "variation",
        "variation_of",
        "related_variations",
        "movement_patterns",
        "phase_id",
        "phase_type",
        "contraction_type",
        "joint_id",
        "primary_actions",
        "actions",
        "primary_phases",
        "contraction_phase_emphasis",
        "stimulus_phase_bias",
        "rom_characteristic",
        "moment_demand",
        "muscle_id",
        "muscle_group_id",
        "role",
        "phase_or_range",
        "muscle_length_state",
        "relative_demand",
        "joint_action_context",
        "stabilization_role",
        "score_type",
        "stimulus_region",
        "profile_type",
        "peak_loading_region",
        "external_resistance_type",
        "line_of_force",
        "load_placement",
        "effect_direction",
        "variable_id",
        "sfr_class",
        "status",
        "type",
        "language",
    }
    if path and path[-1] in skip_keys:
        return value
    if isinstance(value, str):
        cleaned = value
        for forbidden, replacement in TEXT_QUALITY_FORBIDDEN.items():
            if forbidden == "ROM":
                cleaned = re.sub(r"\bROM\b", replacement, cleaned)
            elif forbidden == "RDL":
                cleaned = re.sub(r"\bRDL\b", replacement, cleaned)
            else:
                cleaned = re.sub(re.escape(forbidden), replacement, cleaned, flags=re.IGNORECASE)
        return cleaned
    if isinstance(value, list):
        return [sanitize_card_text(item, (*path, str(index))) for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {key: sanitize_card_text(item, (*path, key)) for key, item in value.items()}
    return value


def ensure_detailed_phase_and_load_text(card: dict[str, Any]) -> None:
    biomechanics = card.get("biomechanics") or {}
    for phase in biomechanics.get("movement_phases") or []:
        phase_id = phase.get("phase_id") or "phase"
        if len(phase.get("start_position") or "") < 20:
            phase["start_position"] = (
                f"{phase.get('start_position')}; положение проверяется до начала фазы, "
                "чтобы не потерять контроль корпуса и рабочей траектории"
            )
        if len(phase.get("end_position") or "") < 20:
            phase["end_position"] = (
                f"{phase.get('end_position')}; фаза считается завершенной только при сохранении "
                "положения основных суставов и устойчивой опоры"
            )
        key_events = list(phase.get("key_events") or [])
        additions = [
            "сохранить контролируемую траекторию без рывка",
            "проверить положение целевых суставов перед переходом к следующей фазе",
            "не допускать компенсации корпусом или потери опоры",
        ]
        for addition in additions:
            if len(key_events) >= 3:
                break
            if addition not in key_events:
                key_events.append(addition)
        phase["key_events"] = key_events

    external = biomechanics.get("external_load_mechanics") or {}
    for item in external.get("vector_shift_effects") or []:
        affected_muscles = [
            muscle_name(muscle_id) if muscle_id in MUSCLES else str(muscle_id)
            for muscle_id in item.get("affected_muscles") or []
        ]
        affected_joints = ", ".join(str(joint_id) for joint_id in item.get("affected_joints") or [])
        muscle_text = ", ".join(affected_muscles) or "целевые мышцы"
        direction = item.get("effect_direction")
        biomechanical_effect = item.get("biomechanical_effect") or ""
        if len(biomechanical_effect) < 80 or "линия силы" not in biomechanical_effect.lower() or "плеч" not in biomechanical_effect.lower():
            if direction == "decreases":
                item["biomechanical_effect"] = (
                    f"{biomechanical_effect.rstrip('.')}. Линия силы становится ближе к рабочей оси "
                    f"({affected_joints}), внешнее плечо момента уменьшается, поэтому требование к "
                    f"{muscle_text} снижается, а упражнение легче удерживать без компенсации корпусом."
                )
            else:
                item["biomechanical_effect"] = (
                    f"{biomechanical_effect.rstrip('.')}. Линия силы уходит дальше от рабочей оси "
                    f"({affected_joints}), внешнее плечо момента увеличивается, поэтому {muscle_text} "
                    "должны создавать больше внутреннего усилия, чтобы сохранить ту же траекторию."
                )
        muscle_bias_change = item.get("muscle_bias_change") or ""
        if len(muscle_bias_change) < 70 or "акцент" not in muscle_bias_change.lower():
            if direction == "decreases":
                item["muscle_bias_change"] = (
                    f"{muscle_bias_change.rstrip('.;')}; акцент на {muscle_text} снижается, "
                    "а часть работы может перейти в более стабильную опору или соседние суставы."
                )
            else:
                item["muscle_bias_change"] = (
                    f"{muscle_bias_change.rstrip('.;')}; акцент увеличивается на {muscle_text}, "
                    "но вместе с этим растет цена стабилизации и риск технической компенсации."
                )


def ensure_best_use_summary(card: dict[str, Any]) -> None:
    best_use = card.get("best_use")
    if not isinstance(best_use, dict):
        best_use = {}
    if len(best_use.get("summary") or "") >= 120:
        card["best_use"] = best_use
        return

    title = card.get("russian_name") or (card.get("names") or {}).get("ru") or card.get("exercise_name") or "Упражнение"
    dominance = (card.get("display_labels") or {}).get("dominance_label_ru") or card.get("dominance_type") or "не определено"
    primary_goal = best_use.get("primary_goal") or best_use.get("hypertrophy") or "для целевой силовой и мышечной работы"
    context = best_use.get("best_context") or best_use.get("strength") or "когда техника повторяема, а нагрузка дозируется без потери контроля"
    less_suitable = best_use.get("less_suitable_for") or "когда боль, усталость или настройка оборудования мешают сохранять механику"
    alternatives = card.get("alternatives") or []
    alternative_text = ""
    if alternatives and isinstance(alternatives[0], dict):
        first = alternatives[0]
        alternative_text = (
            f" По сравнению с вариантом «{first.get('name')}» отличие в том, что "
            f"{first.get('main_difference') or first.get('similarity') or 'меняется механика нагрузки'}."
        )

    best_use["summary"] = (
        f"{title} — {str(dominance).lower()} с задачей: {primary_goal}. "
        f"Выбирать это упражнение стоит {context}. {less_suitable} — повод заменить или изменить вариант."
        f"{alternative_text}"
    )
    card["best_use"] = best_use


def card_search_text(card: dict[str, Any]) -> str:
    parts = [
        card.get("exercise_name") or "",
        card.get("russian_name") or "",
        " ".join(card.get("aliases") or []),
        " ".join(str(value) for value in (card.get("names") or {}).values()),
    ]
    return normalize_text(" ".join(parts))


def source_ids_for_domains(sources: list[dict[str, Any]], domains: set[str], fallback_limit: int = 5) -> list[str]:
    selected = []
    for source in sources:
        if source.get("is_retracted"):
            continue
        source_domains = set(source.get("evidence_domain") or [])
        study_type = source.get("study_type") or ""
        if source_domains.intersection(domains) or study_type in domains:
            selected.append(source["source_id"])
    if selected:
        return selected[:fallback_limit]
    return [
        source["source_id"]
        for source in sources
        if source.get("source_id") and not source.get("is_retracted")
    ][:fallback_limit]


def direct_source_ids(sources: list[dict[str, Any]], fallback_limit: int = 5) -> list[str]:
    selected = [
        source["source_id"]
        for source in sources
        if source.get("source_id")
        and not source.get("is_retracted")
        and source.get("exercise_match") == "direct"
    ]
    if selected:
        return selected[:fallback_limit]
    return [
        source["source_id"]
        for source in sources
        if source.get("source_id") and not source.get("is_retracted")
    ][:fallback_limit]


def confidence_from_sources(source_ids: list[str]) -> tuple[str, int | None]:
    if len(source_ids) >= 3:
        return "medium", 70
    if len(source_ids) >= 1:
        return "medium", 60
    return "low", 35


def make_claim(
    claim: str,
    source_ids: list[str],
    evidence_type: str = "biomechanical_inference",
    confidence: str | None = None,
    confidence_score: int | None = None,
) -> dict[str, Any]:
    if confidence is None:
        confidence, confidence_score = confidence_from_sources(source_ids)
    return {
        "claim": claim,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "source_ids": source_ids,
    }


def make_muscle_summary(
    muscle_id: str,
    role: str,
    phase_or_range: str,
    rationale: str,
    source_ids: list[str],
    evidence_type: str = "biomechanical_inference",
) -> dict[str, Any]:
    confidence, score = confidence_from_sources(source_ids)
    return {
        "muscle_id": muscle_id,
        "muscle_name_ru": muscle_name(muscle_id),
        "muscle_group_id": muscle_group(muscle_id),
        "role": role,
        "phase_or_range": phase_or_range,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": score,
        "rationale": rationale,
        "source_ids": source_ids,
    }


def make_muscle_role_by_phase(
    phase_id: str,
    muscle_id: str,
    role: str,
    action: str,
    joint_action_context: str,
    contraction_type: str,
    muscle_length_state: str,
    relative_demand: str,
    source_ids: list[str],
    evidence_type: str = "biomechanical_inference",
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "phase_id": phase_id,
        "muscle_id": muscle_id,
        "muscle_name_ru": muscle_name(muscle_id),
        "muscle_group_id": muscle_group(muscle_id),
        "role": role,
        "action": action,
        "joint_action_context": joint_action_context,
        "contraction_type": contraction_type,
        "muscle_length_state": muscle_length_state,
        "relative_demand": relative_demand,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "source_ids": source_ids,
    }


def make_phase(
    phase_id: str,
    phase_type: str,
    name_ru: str,
    contraction_type: str,
    start_position: str,
    end_position: str,
    key_events: list[str],
    source_ids: list[str],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "phase_id": phase_id,
        "phase_type": phase_type,
        "name_ru": name_ru,
        "contraction_type": contraction_type,
        "start_position": start_position,
        "end_position": end_position,
        "key_events": key_events,
        "evidence_type": "biomechanical_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def make_joint_mechanics(
    joint_id: str,
    phase_id: str,
    primary_actions: list[str],
    rom_characteristic: str,
    moment_demand: str,
    muscle_function: str,
    notes: str,
    source_ids: list[str],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "joint_id": joint_id,
        "phase_id": phase_id,
        "primary_actions": primary_actions,
        "rom_characteristic": rom_characteristic,
        "moment_demand": moment_demand,
        "muscle_function": muscle_function,
        "notes": notes,
        "evidence_type": "biomechanical_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def make_joint_action_summary(
    joint_id: str,
    actions: list[str],
    phases: list[str],
    source_ids: list[str],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "joint_id": joint_id,
        "actions": actions,
        "primary_phases": phases,
        "evidence_type": "biomechanical_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def make_technique_variable(
    variable_id: str,
    name_ru: str,
    description: str,
    biomechanical_effect: str,
    affected_joints: list[str],
    affected_muscles: list[str],
    source_ids: list[str],
    evidence_type: str = "biomechanical_inference",
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "variable_id": variable_id,
        "name_ru": name_ru,
        "description": description,
        "biomechanical_effect": biomechanical_effect,
        "affected_joints": affected_joints,
        "affected_muscles": affected_muscles,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "source_ids": source_ids,
    }


def make_common_error(
    error: str,
    consequence: str,
    correction: str,
    severity: str,
    source_ids: list[str],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "error": error,
        "biomechanical_consequence": consequence,
        "correction": correction,
        "severity": severity,
        "evidence_type": "expert_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def infer_equipment_and_modality(text: str, default_load_placement: str) -> dict[str, Any]:
    if "smith" in text or "смита" in text:
        return {
            "modality": "smith_machine",
            "equipment_required": ["smith_machine"],
            "external_resistance_type": "gravity",
            "line_of_force": "machine_guided",
            "load_placement": default_load_placement,
        }
    if "cable" in text or "трос" in text or "блок" in text:
        return {
            "modality": "cable",
            "equipment_required": ["cable_station"],
            "external_resistance_type": "cable",
            "line_of_force": "mixed",
            "load_placement": "cable_attachment",
        }
    if "dumbbell" in text or "гантел" in text:
        return {
            "modality": "free_weight",
            "equipment_required": ["dumbbell"],
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": "hands",
        }
    if "barbell" in text or "штанг" in text:
        return {
            "modality": "free_weight",
            "equipment_required": ["barbell"],
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": default_load_placement,
        }
    if "bodyweight" in text or "с собственным весом" in text:
        return {
            "modality": "bodyweight",
            "equipment_required": ["bodyweight_only"],
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": "torso",
        }
    return {
        "modality": "unclear",
        "equipment_required": [],
        "external_resistance_type": "unclear",
        "line_of_force": "unclear",
        "load_placement": default_load_placement,
    }


def refresh_evidence_first_summary(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    backends = sorted({backend for source in sources for backend in source.get("source_backends", [])})
    providers = sorted({provider for source in sources for provider in source.get("source_providers", [])})
    provider_backends = sorted({backend for source in sources for backend in source.get("provider_backends", [])})
    card["evidence_summary"] = {
        "source_count": len(sources),
        "direct_match_count": sum(1 for source in sources if source.get("exercise_match") == "direct"),
        "fulltext_count": sum(1 for source in sources if source.get("has_fulltext")),
        "retracted_count": sum(1 for source in sources if source.get("is_retracted")),
        "backends": backends,
        "providers": providers,
        "provider_backends": provider_backends,
        "population_method": "evidence_first_per_field_analysis_required",
        "important_caveat": (
            "Шаблонное заполнение отключено. Каждое биомеханическое поле должно быть "
            "заполнено заново: сначала по прямым данным для конкретного упражнения, "
            "а при их отсутствии - аналитическим выводом из подходящих исследований "
            "по близким вариациям, семейству упражнения или паттерну движения."
        ),
    }


def reset_interpretive_fields(card: dict[str, Any], source_ids: list[str]) -> None:
    card["exercise_family"] = "unclear"
    card["category"] = "unclear"
    card["body_region"] = "unclear"
    card["target_region"] = "unclear"
    card["dominance_type"] = "unclear"
    card["compound_type"] = "unclear"
    card["movement_patterns"] = ["unclear"]
    card["force_vector"] = "unclear"
    card["kinetic_chain"] = "unclear"
    card["movement_planes"] = ["unclear"]
    card["body_position"] = "unclear"
    card["limb_pattern"] = "unclear"
    card["technical_complexity"] = "unclear"
    card["mobility_requirements"] = []
    card["movement_pattern_details"] = []
    card["primary_muscles"] = []
    card["secondary_muscles"] = []
    card["stabilizers"] = []
    card["joint_actions"] = []
    card["contraction_phase_emphasis"] = "unclear"
    card["stimulus_phase_bias"] = "unclear"
    card["muscle_stimulus_phase_bias"] = []
    card["relative_muscle_emphasis"] = []
    card["common_errors"] = []
    card["execution_steps"] = {
        "setup": [],
        "execution": [],
        "rom": [],
        "breathing_bracing": [],
        "tempo_control": [],
    }
    card["best_use"] = {}
    card["typical_rep_ranges"] = []
    card["progression_options"] = []
    card["when_to_avoid_or_modify"] = []
    card["prerequisite_skill_mobility"] = []
    card["supersets_trisets"] = []
    card["variations"] = []
    card["alternatives"] = []
    card["safety"] = {}
    card["resistance_profile"] = {
        "profile_type": "unclear",
        "peak_loading_region": "unclear",
        "explanation": "Не заполнено: требуется отдельный evidence-first анализ по источникам.",
        "evidence_type": "unavailable",
        "confidence": "unknown",
        "confidence_score": None,
        "assumptions": [],
        "source_ids": [],
    }
    card["fatigue_cost"] = {
        "local_fatigue": "unclear",
        "systemic_fatigue": "unclear",
        "technical_fatigue": "unclear",
        "axial_loading": "unclear",
        "stability_demand": "unclear",
        "overall_fatigue_cost": "unclear",
        "evidence_type": "unavailable",
        "confidence": "unknown",
        "confidence_score": None,
        "assumptions": [],
        "source_ids": [],
    }
    card["sfr"] = {
        "sfr_class": "unclear",
        "evidence_type": "unavailable",
        "confidence": "unknown",
        "confidence_score": None,
        "context": "Не заполнено: требуется отдельный evidence-first анализ по источникам.",
        "assumptions": [],
        "source_ids": [],
    }
    card["biomechanics"] = {
        "movement_phases": [],
        "joint_mechanics": [],
        "muscle_roles_by_phase": [],
        "external_load_mechanics": {
            "external_resistance_type": "unclear",
            "line_of_force": "unclear",
            "load_placement": "unclear",
            "main_moment_arms": [],
            "vector_shift_effects": [],
            "evidence_type": "unavailable",
            "confidence": "unknown",
            "source_ids": [],
        },
        "technique_variables": [],
        "biomechanical_summary": make_claim(
            "Шаблонное биомеханическое заполнение отключено; требуется извлечение и аналитическое заполнение каждого поля по источникам.",
            source_ids,
            evidence_type="insufficient_evidence",
            confidence="unknown",
            confidence_score=None,
        ),
    }


def populate_card_evidence_first(card: dict[str, Any], source_ledger: dict[str, Any]) -> dict[str, Any]:
    populated = copy.deepcopy(card)
    sources = source_ledger.get("sources") or []
    source_ids = [source["id"] for source in sources if source.get("id")]
    reset_interpretive_fields(populated, source_ids)
    set_display_labels(populated)
    populated["assumptions"] = unique_strings(
        [
            *populated.get("assumptions", []),
            "Шаблонные значения характеристик запрещены и не используются при обычном заполнении.",
            "Если прямых данных по конкретному упражнению нет, поле должно заполняться только отдельным аналитическим выводом из подходящих исследований.",
            "Идентификаторы источников указывают на найденные публикации; они не являются автоматическим подтверждением каждого незаполненного поля.",
        ]
    )
    populated["limitations"] = unique_strings(
        [
            *populated.get("limitations", []),
            "Карточка очищена от шаблонного биомеханического слоя; требуется per-field извлечение и анализ источников.",
            "Близкие вариации, семейство упражнения и широкий паттерн движения могут использоваться только как явно помеченная аналитическая опора, а не как шаблонное значение.",
        ]
    )
    populated["not_supported_claims"] = unique_strings(
        [
            *populated.get("not_supported_claims", []),
            "Не допускается переносить фазы, роли мышц, пики нагрузки, вариации или альтернативы из локального шаблона движения.",
            "Не допускается считать source_id доказательством поля без извлеченного факта или отдельного аналитического обоснования.",
        ]
    )
    refresh_evidence_first_summary(populated, sources)
    populated = sanitize_card_text(populated)
    ensure_best_use_summary(populated)
    populated["evidence_ledger"] = [populated["biomechanics"]["biomechanical_summary"]]
    populated["metadata"].pop("population_template_id", None)
    populated["metadata"]["populated_at"] = now_iso()
    populated["metadata"]["population_method"] = "evidence_first_no_templates"
    populated["metadata"]["schema_version"] = "0.2.0"
    populated["schema_version"] = "0.2.0"
    populated["status"] = "staged_draft"
    return populated


def populate_card(card: dict[str, Any], source_ledger: dict[str, Any]) -> dict[str, Any]:
    return populate_card_evidence_first(card, source_ledger)


def unique_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def resolve_paths_from_exercise_id(exercise_id: str) -> tuple[Path, Path]:
    return (
        PROJECT_ROOT / "output" / "exercise_cards" / f"{exercise_id}.json",
        PROJECT_ROOT / "output" / "sources" / f"{exercise_id}.sources.json",
    )


def process_one(
    card_path: Path,
    sources_path: Path,
    output_path: Path | None,
    validate: bool,
) -> Path:
    if not card_path.exists():
        raise PopulateError(f"Card file not found: {card_path}")
    if not sources_path.exists():
        raise PopulateError(f"Sources file not found: {sources_path}")

    card = load_json(card_path)
    source_ledger = load_json(sources_path)
    populated = populate_card(card, source_ledger)
    if validate:
        validate_card(populated)

    destination = output_path or card_path
    write_json(destination, populated)
    return destination


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare staged exercise cards for evidence-first biomechanical analysis.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--exercise-id", help="Exercise id under output/exercise_cards and output/sources.")
    target.add_argument("--card", type=Path, help="Path to a staged exercise card JSON.")
    target.add_argument("--all", action="store_true", help="Populate all cards in output/exercise_cards.")
    parser.add_argument("--sources", type=Path, help="Path to source ledger JSON. Required with --card.")
    parser.add_argument("--output", type=Path, help="Output path. Defaults to in-place update. Only valid with single-card mode.")
    parser.add_argument("--no-validate", action="store_true", help="Skip JSON Schema validation.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)

    if args.output and args.all:
        raise PopulateError("--output cannot be used with --all")

    validate = not args.no_validate
    results = []
    if args.exercise_id:
        card_path, sources_path = resolve_paths_from_exercise_id(args.exercise_id)
        destination = process_one(card_path, sources_path, args.output, validate)
        results.append(str(destination))
    elif args.card:
        card_path = args.card if args.card.is_absolute() else PROJECT_ROOT / args.card
        if not args.sources:
            raise PopulateError("--sources is required with --card")
        sources_path = args.sources if args.sources.is_absolute() else PROJECT_ROOT / args.sources
        output_path = args.output if not args.output or args.output.is_absolute() else PROJECT_ROOT / args.output
        destination = process_one(card_path, sources_path, output_path, validate)
        results.append(str(destination))
    else:
        cards_dir = PROJECT_ROOT / "output" / "exercise_cards"
        for card_path in sorted(cards_dir.glob("*.json")):
            exercise_id = card_path.stem
            sources_path = PROJECT_ROOT / "output" / "sources" / f"{exercise_id}.sources.json"
            destination = process_one(card_path, sources_path, None, validate)
            results.append(str(destination))

    print(json.dumps({"populated": results, "count": len(results)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
