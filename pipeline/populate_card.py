#!/usr/bin/env python
"""
Populate staged exercise cards with structured biomechanical content.

This step reads:
- output/exercise_cards/<exercise_id>.json
- output/sources/<exercise_id>.sources.json

It writes a schema-valid card with deterministic classification fields,
movement phases, joint mechanics, muscle roles by phase, load mechanics, and
practical programming fields.

The first version is intentionally conservative: it uses controlled movement
templates and attaches source IDs from the merged Amass + NCBI source ledger.
Claims that are not directly extracted from papers are marked as
biomechanical_inference or expert_inference.
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


def muscle_name(muscle_id: str) -> str:
    return MUSCLES[muscle_id].name_ru


def muscle_group(muscle_id: str) -> str:
    return MUSCLES[muscle_id].group_id


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


def match_template(card: dict[str, Any]) -> str:
    text = card_search_text(card)
    checks = [
        ("romanian_deadlift", [r"\brdl\b", r"romanian deadlift", r"румын"]),
        ("hip_thrust", [r"hip thrust", r"glute bridge", r"ягодичн.*мост", r"хип\s*траст"]),
        ("bench_press", [r"bench press", r"жим.*леж", r"жим.*скам"]),
        ("deadlift", [r"\bdeadlift\b", r"станов"]),
        ("split_squat", [r"split squat", r"bulgarian", r"lunge", r"выпад", r"болгар"]),
        ("squat", [r"\bsquat\b", r"присед"]),
    ]
    for template_id, patterns in checks:
        if any(re.search(pattern, text) for pattern in patterns):
            return template_id
    return "unknown"


def source_context(sources: list[dict[str, Any]]) -> dict[str, list[str]]:
    biomech_domains = {"biomechanics", "kinematics", "kinetics", "emg", "muscle_activation"}
    review_domains = {"systematic_review", "meta_analysis", "review"}
    return {
        "all": direct_source_ids(sources),
        "biomech": source_ids_for_domains(sources, biomech_domains),
        "reviews": source_ids_for_domains(sources, review_domains),
        "fatigue": source_ids_for_domains(sources, {"fatigue", "injury_risk"}),
        "technique": source_ids_for_domains(sources, {"technique", "equipment", "kinematics", "kinetics"}),
    }


def base_external_load(
    equipment: dict[str, Any],
    source_ids: list[str],
    main_moment_arms: list[dict[str, Any]],
    vector_shift_effects: list[dict[str, Any]],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "external_resistance_type": equipment["external_resistance_type"],
        "line_of_force": equipment["line_of_force"],
        "load_placement": equipment["load_placement"],
        "main_moment_arms": main_moment_arms,
        "vector_shift_effects": vector_shift_effects,
        "evidence_type": "biomechanical_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def moment_arm(joint_id: str, condition: str, effect: str, muscles: list[str]) -> dict[str, Any]:
    return {
        "joint_id": joint_id,
        "condition": condition,
        "effect": effect,
        "affected_muscles": muscles,
    }


def vector_effect(
    change: str,
    effect_direction: str,
    joints: list[str],
    muscles: list[str],
    biomechanical_effect: str,
    muscle_bias_change: str,
    source_ids: list[str],
) -> dict[str, Any]:
    confidence, _ = confidence_from_sources(source_ids)
    return {
        "change": change,
        "effect_direction": effect_direction,
        "affected_joints": joints,
        "affected_muscles": muscles,
        "biomechanical_effect": biomechanical_effect,
        "muscle_bias_change": muscle_bias_change,
        "evidence_type": "biomechanical_inference",
        "confidence": confidence,
        "source_ids": source_ids,
    }


def apply_squat_template(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    ctx = source_context(sources)
    text = card_search_text(card)
    equipment = infer_equipment_and_modality(text, default_load_placement="shoulders")
    biomech = ctx["biomech"]
    technique = ctx["technique"]

    card.update(
        {
            "exercise_family": "squat",
            "category": "lower_body_strength",
            "body_region": "lower_body",
            "target_region": "quadriceps",
            "dominance_type": "knee_dominant",
            "modality": equipment["modality"],
            "equipment_required": equipment["equipment_required"],
            "compound_type": "compound",
            "movement_patterns": ["squat"],
            "force_vector": "vertical",
            "kinetic_chain": "closed_chain",
            "movement_planes": ["sagittal"],
            "body_position": "standing",
            "limb_pattern": "bilateral",
            "technical_complexity": "moderate",
            "mobility_requirements": [
                "достаточная дорсифлексия голеностопа",
                "контроль сгибания бедра и колена",
                "способность удерживать нейтральное положение корпуса",
            ],
            "contraction_phase_emphasis": "mixed",
            "stimulus_phase_bias": "lengthened",
        }
    )

    card["primary_muscles"] = [
        make_muscle_summary("vastus_lateralis", "prime_mover", "lengthened", "Создает разгибание колена, особенно при подъеме из нижней части амплитуды.", biomech),
        make_muscle_summary("vastus_medialis", "prime_mover", "lengthened", "Участвует в разгибании колена и стабилизации коленного сустава.", biomech),
        make_muscle_summary("rectus_femoris", "synergist", "mixed", "Вносит вклад в разгибание колена, но его роль зависит от углов бедра и колена.", biomech),
        make_muscle_summary("lower_gluteus_maximus", "prime_mover", "lengthened", "Создает разгибание бедра при подъеме из нижней части приседа.", biomech),
        make_muscle_summary("upper_gluteus_maximus", "synergist", "lengthened", "Помогает разгибанию бедра и контролю таза.", biomech),
    ]
    card["secondary_muscles"] = [
        make_muscle_summary("hip_adductors", "synergist", "lengthened", "Приводящие могут помогать разгибанию бедра в нижней части приседа.", biomech),
        make_muscle_summary("hamstrings", "dynamic_stabilizer", "mixed", "Помогают контролю тазобедренного сустава, но не являются главным разгибателем колена.", biomech),
        make_muscle_summary("gastrocnemius", "dynamic_stabilizer", "mixed", "Помогает контролю голени и голеностопа.", biomech),
    ]
    card["stabilizers"] = [
        {**make_muscle_summary("spinal_erectors", "stabilizer", "mixed", "Удерживают позвоночник от сгибания под внешней нагрузкой.", biomech), "stabilization_role": "anti_flexion"},
        {**make_muscle_summary("transverse_abdominis", "stabilizer", "mixed", "Поддерживает внутрибрюшное давление и жесткость корпуса.", technique), "stabilization_role": "bracing"},
        {**make_muscle_summary("obliques", "stabilizer", "mixed", "Помогают контролировать боковое смещение и ротацию корпуса.", technique), "stabilization_role": "anti_rotation"},
    ]

    card["joint_actions"] = [
        make_joint_action_summary("hip", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("knee", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("ankle", ["dorsiflexion", "plantar_flexion"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("lumbar_spine", ["anti_flexion", "stabilization"], ["eccentric_descent", "concentric_ascent"], technique),
    ]

    phases = [
        make_phase("setup", "setup", "настройка", "isometric", "атлет стоит под нагрузкой", "стопы и корпус зафиксированы", ["выбор стойки", "брейсинг", "позиция грифа/снаряда"], technique),
        make_phase("eccentric_descent", "eccentric", "опускание", "eccentric", "таз и колени разогнуты", "таз и колени согнуты, достигнута нижняя позиция", ["сгибание бедра и колена", "дорсифлексия голеностопа", "контроль корпуса"], biomech),
        make_phase("bottom_transition", "bottom_transition", "нижний переход", "stretch_shortening_cycle", "нижняя позиция", "начало подъема", ["смена направления", "максимальные требования к контролю колена и бедра"], biomech),
        make_phase("concentric_ascent", "concentric", "подъем", "concentric", "нижняя позиция", "таз и колени разогнуты", ["разгибание колена", "разгибание бедра", "сохранение траектории центра массы"], biomech),
        make_phase("top_position", "top_position", "верхняя позиция", "isometric", "подъем завершен", "стабильная вертикальная позиция", ["фиксация корпуса", "подготовка к следующему повторению"], technique),
    ]
    card["biomechanics"]["movement_phases"] = phases
    card["biomechanics"]["joint_mechanics"] = [
        make_joint_mechanics("hip", "eccentric_descent", ["flexion"], "large", "high", "разгибатели бедра контролируют сгибание бедра эксцентрически", "Чем больше наклон корпуса и плечо момента относительно таза, тем выше требование к разгибателям бедра.", biomech),
        make_joint_mechanics("knee", "eccentric_descent", ["flexion"], "large", "high", "квадрицепс контролирует сгибание колена эксцентрически", "Большая передняя подача колена обычно повышает требования к разгибателям колена.", biomech),
        make_joint_mechanics("ankle", "eccentric_descent", ["dorsiflexion"], "moderate", "moderate", "мышцы голени контролируют положение стопы и голени", "Ограничение дорсифлексии может менять глубину и наклон корпуса.", biomech),
        make_joint_mechanics("hip", "concentric_ascent", ["extension"], "large", "high", "ягодичные и приводящие помогают разгибать бедро", "Вклад разгибателей бедра обычно возрастает при большем наклоне корпуса.", biomech),
        make_joint_mechanics("knee", "concentric_ascent", ["extension"], "large", "high", "квадрицепс создает разгибание колена", "Подъем из нижней части требует высокого момента разгибания колена.", biomech),
        make_joint_mechanics("lumbar_spine", "concentric_ascent", ["anti_flexion", "stabilization"], "near_isometric", "moderate", "разгибатели позвоночника и мышцы кора удерживают корпус", "Нагрузка на разгибатели позвоночника растет, если снаряд смещается вперед или корпус чрезмерно наклоняется.", technique),
    ]
    card["biomechanics"]["muscle_roles_by_phase"] = [
        make_muscle_role_by_phase("eccentric_descent", "vastus_lateralis", "prime_mover", "эксцентрически контролирует сгибание колена", "knee_flexion_control", "eccentric", "lengthening", "high", biomech),
        make_muscle_role_by_phase("eccentric_descent", "lower_gluteus_maximus", "prime_mover", "эксцентрически контролирует сгибание бедра", "hip_flexion_control", "eccentric", "lengthening", "high", biomech),
        make_muscle_role_by_phase("eccentric_descent", "spinal_erectors", "stabilizer", "удерживает позвоночник от сгибания", "lumbar_anti_flexion", "isometric", "near_isometric", "moderate", technique),
        make_muscle_role_by_phase("concentric_ascent", "vastus_lateralis", "prime_mover", "создает разгибание колена", "knee_extension", "concentric", "shortening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "lower_gluteus_maximus", "prime_mover", "создает разгибание бедра", "hip_extension", "concentric", "shortening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "hip_adductors", "synergist", "помогает разгибанию бедра из глубокой позиции", "hip_extension_assistance", "concentric", "shortening", "moderate", biomech),
    ]
    card["biomechanics"]["external_load_mechanics"] = base_external_load(
        equipment,
        technique,
        [
            moment_arm("knee", "колено сильнее смещается вперед относительно стопы", "увеличивается требование к разгибателям колена", ["vastus_lateralis", "vastus_medialis", "rectus_femoris"]),
            moment_arm("hip", "корпус наклоняется сильнее или гриф расположен ниже/дальше назад", "увеличивается требование к разгибателям бедра и спины", ["lower_gluteus_maximus", "upper_gluteus_maximus", "spinal_erectors"]),
        ],
        [
            vector_effect("более вертикальный корпус", "shifts", ["knee", "hip"], ["vastus_lateralis", "vastus_medialis"], "нагрузка смещается в сторону большего коленного момента", "относительно больше акцент на квадрицепс", technique),
            vector_effect("больший наклон корпуса", "shifts", ["hip", "lumbar_spine"], ["lower_gluteus_maximus", "spinal_erectors"], "увеличивается плечо момента относительно бедра и позвоночника", "относительно больше акцент на ягодичные и разгибатели спины", technique),
        ],
    )
    card["biomechanics"]["technique_variables"] = [
        make_technique_variable("stance_width", "ширина стойки", "Изменяет положение бедра, колена и таза.", "Может менять вклад приводящих, ягодичных и глубину доступной амплитуды.", ["hip", "knee"], ["hip_adductors", "lower_gluteus_maximus", "vastus_lateralis"], technique),
        make_technique_variable("bar_position", "положение грифа/нагрузки", "Высокое, низкое или переднее положение нагрузки меняет плечи момента.", "Переднее/высокое положение обычно поддерживает более вертикальный корпус; низкое положение часто увеличивает hip-dominant стратегию.", ["hip", "knee", "lumbar_spine"], ["vastus_lateralis", "lower_gluteus_maximus", "spinal_erectors"], technique),
        make_technique_variable("depth", "глубина приседа", "Определяет конечные углы бедра и колена.", "Большая глубина повышает требования к контролю в растянутой позиции при достаточной мобильности.", ["hip", "knee", "ankle"], ["vastus_lateralis", "lower_gluteus_maximus", "hip_adductors"], technique),
    ]
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Присед является многосуставным паттерном с основными требованиями к разгибанию колена и бедра; распределение нагрузки между квадрицепсом, ягодичными и разгибателями позвоночника зависит от глубины, наклона корпуса, положения нагрузки и антропометрии.",
        biomech,
    )
    card["resistance_profile"] = {
        "profile_type": "ascending",
        "peak_loading_region": "bottom",
        "explanation": "Для свободного приседа механические требования часто максимальны в нижней части и в начальном подъеме, где велики моменты в колене и бедре.",
        "evidence_type": "biomechanical_inference",
        "confidence": confidence_from_sources(biomech)[0],
        "confidence_score": confidence_from_sources(biomech)[1],
        "assumptions": ["Свободный вес или близкая к нему механика.", "Техника без выраженных компенсаций."],
        "source_ids": biomech,
    }
    card["muscle_stimulus_phase_bias"] = [
        {"muscle_id": "vastus_lateralis", "stimulus_region": "lengthened", "rationale": "Высокие требования в нижней части амплитуды при согнутом колене.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
        {"muscle_id": "lower_gluteus_maximus", "stimulus_region": "lengthened", "rationale": "Высокие требования при согнутом бедре в нижней части приседа.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
    ]
    card["relative_muscle_emphasis"] = [
        relative_emphasis("vastus_lateralis", 85, "Основной разгибатель колена в приседе.", biomech),
        relative_emphasis("vastus_medialis", 80, "Сильный вклад в разгибание колена.", biomech),
        relative_emphasis("lower_gluteus_maximus", 75, "Сильный вклад в разгибание бедра, особенно при глубокой амплитуде.", biomech),
        relative_emphasis("hip_adductors", 55, "Синергист разгибания бедра, особенно в нижних углах.", biomech),
    ]
    fill_common_practical_fields(card, source_ids=technique, profile="squat")


def apply_hinge_template(card: dict[str, Any], sources: list[dict[str, Any]], romanian: bool) -> None:
    ctx = source_context(sources)
    text = card_search_text(card)
    equipment = infer_equipment_and_modality(text, default_load_placement="hands")
    biomech = ctx["biomech"]
    technique = ctx["technique"]
    family = "romanian_deadlift" if romanian else "deadlift"

    card.update(
        {
            "exercise_family": family,
            "category": "lower_body_strength",
            "body_region": "lower_body",
            "target_region": "hamstrings" if romanian else "full_body",
            "dominance_type": "hip_dominant" if romanian else "balanced",
            "modality": equipment["modality"],
            "equipment_required": equipment["equipment_required"],
            "compound_type": "compound",
            "movement_patterns": ["hinge"],
            "force_vector": "vertical",
            "kinetic_chain": "closed_chain",
            "movement_planes": ["sagittal"],
            "body_position": "standing",
            "limb_pattern": "bilateral",
            "technical_complexity": "moderate" if romanian else "high",
            "mobility_requirements": [
                "контроль тазобедренного шарнира",
                "способность удерживать нейтральный позвоночник",
                "достаточная подвижность задней поверхности бедра",
            ],
            "contraction_phase_emphasis": "mixed",
            "stimulus_phase_bias": "lengthened",
        }
    )

    card["primary_muscles"] = [
        make_muscle_summary("hamstrings", "prime_mover", "lengthened", "Контролируют сгибание бедра при опускании и помогают разгибанию бедра при подъеме.", biomech),
        make_muscle_summary("lower_gluteus_maximus", "prime_mover", "lengthened", "Создает разгибание бедра при подъеме.", biomech),
        make_muscle_summary("upper_gluteus_maximus", "synergist", "mixed", "Помогает разгибанию бедра и контролю таза.", biomech),
    ]
    if not romanian:
        card["primary_muscles"].extend(
            [
                make_muscle_summary("vastus_lateralis", "synergist", "mixed", "Помогает разгибанию колена при отрыве снаряда от пола.", biomech),
                make_muscle_summary("spinal_erectors", "stabilizer", "mixed", "Удерживает позвоночник от сгибания под нагрузкой.", biomech),
            ]
        )
    card["secondary_muscles"] = [
        make_muscle_summary("hip_adductors", "synergist", "lengthened", "Может помогать разгибанию бедра и стабилизации таза.", biomech),
        make_muscle_summary("forearm_grip", "stabilizer", "mixed", "Удерживает снаряд в руках.", technique),
    ]
    card["stabilizers"] = [
        {**make_muscle_summary("spinal_erectors", "stabilizer", "mixed", "Удерживают нейтральное положение позвоночника.", biomech), "stabilization_role": "anti_flexion"},
        {**make_muscle_summary("transverse_abdominis", "stabilizer", "mixed", "Поддерживает брейсинг и жесткость корпуса.", technique), "stabilization_role": "bracing"},
        {**make_muscle_summary("lower_lats", "stabilizer", "mixed", "Помогает удерживать снаряд ближе к телу и контролировать плечевой пояс.", technique), "stabilization_role": "bar_path_control"},
    ]
    card["joint_actions"] = [
        make_joint_action_summary("hip", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("knee", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("lumbar_spine", ["anti_flexion", "stabilization"], ["eccentric_descent", "concentric_ascent"], technique),
        make_joint_action_summary("scapulothoracic", ["stabilization"], ["eccentric_descent", "concentric_ascent"], technique),
    ]

    if romanian:
        phases = [
            make_phase("setup", "setup", "настройка", "isometric", "стойка с нагрузкой в руках", "корпус зафиксирован, колени слегка согнуты", ["брейсинг", "фиксация лопаток", "снаряд близко к бедрам"], technique),
            make_phase("eccentric_descent", "eccentric", "опускание", "eccentric", "таз разогнут, снаряд у бедер", "таз отведен назад, хамстринги растянуты", ["сгибание бедра", "небольшое сгибание колена", "снаряд движется близко к ногам"], biomech),
            make_phase("bottom_transition", "bottom_transition", "нижний переход", "isometric", "конец доступной амплитуды", "начало подъема", ["сохранение нейтрального позвоночника", "контроль растянутой позиции"], biomech),
            make_phase("concentric_ascent", "concentric", "подъем", "concentric", "таз согнут", "таз разогнут", ["разгибание бедра", "снаряд остается близко к телу"], biomech),
            make_phase("top_position", "top_position", "верхняя позиция", "isometric", "таз разогнут", "стабильная стойка", ["фиксация таза без переразгибания поясницы"], technique),
        ]
    else:
        phases = [
            make_phase("setup", "setup", "стартовая настройка", "isometric", "снаряд на полу", "корпус и хват зафиксированы", ["брейсинг", "позиция таза", "снаряд близко к середине стопы"], technique),
            make_phase("concentric_ascent", "concentric", "подъем с пола", "concentric", "снаряд на полу", "снаряд поднят до вертикальной стойки", ["разгибание колена и бедра", "удержание позвоночника", "контроль траектории снаряда"], biomech),
            make_phase("lockout", "lockout", "фиксация", "isometric", "снаряд поднят", "таз и колени разогнуты", ["завершение разгибания бедра", "фиксация корпуса"], technique),
            make_phase("eccentric_descent", "eccentric", "возврат вниз", "eccentric", "верхняя позиция", "снаряд возвращен к полу", ["контроль сгибания бедра и колена", "сохранение близкой траектории"], biomech),
        ]
    card["biomechanics"]["movement_phases"] = phases
    card["biomechanics"]["joint_mechanics"] = [
        make_joint_mechanics("hip", "eccentric_descent", ["flexion"], "large", "high", "хамстринги и ягодичные контролируют сгибание бедра", "Плечо момента относительно бедра растет при удалении снаряда от тела.", biomech),
        make_joint_mechanics("hip", "concentric_ascent", ["extension"], "large", "high", "ягодичные и хамстринги разгибают бедро", "В румынской тяге колено меняет угол меньше, чем в классической тяге.", biomech),
        make_joint_mechanics("knee", "eccentric_descent", ["flexion"], "small" if romanian else "moderate", "low" if romanian else "moderate", "квадрицепс контролирует угол колена", "Большее сгибание колена снижает растяжение хамстрингов и меняет вклад мышц.", biomech),
        make_joint_mechanics("lumbar_spine", "eccentric_descent", ["anti_flexion", "stabilization"], "near_isometric", "high", "разгибатели позвоночника стабилизируют корпус", "Смещение нагрузки вперед увеличивает требования к антифлексии.", technique),
    ]
    card["biomechanics"]["muscle_roles_by_phase"] = [
        make_muscle_role_by_phase("eccentric_descent", "hamstrings", "prime_mover", "эксцентрически контролируют сгибание бедра", "hip_flexion_control", "eccentric", "lengthening", "high", biomech),
        make_muscle_role_by_phase("eccentric_descent", "lower_gluteus_maximus", "prime_mover", "контролирует сгибание бедра", "hip_flexion_control", "eccentric", "lengthening", "moderate", biomech),
        make_muscle_role_by_phase("eccentric_descent", "spinal_erectors", "stabilizer", "удерживает позвоночник от сгибания", "lumbar_anti_flexion", "isometric", "near_isometric", "high", technique),
        make_muscle_role_by_phase("concentric_ascent", "hamstrings", "prime_mover", "помогают разгибать бедро", "hip_extension", "concentric", "shortening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "lower_gluteus_maximus", "prime_mover", "создает разгибание бедра", "hip_extension", "concentric", "shortening", "high", biomech),
    ]
    card["biomechanics"]["external_load_mechanics"] = base_external_load(
        equipment,
        technique,
        [
            moment_arm("hip", "снаряд находится дальше от тазобедренного сустава", "увеличивается требование к разгибателям бедра", ["hamstrings", "lower_gluteus_maximus"]),
            moment_arm("lumbar_spine", "снаряд уходит вперед от тела", "увеличивается требование к разгибателям позвоночника и брейсингу", ["spinal_erectors", "transverse_abdominis"]),
        ],
        [
            vector_effect("снаряд ближе к телу", "decreases", ["hip", "lumbar_spine"], ["spinal_erectors"], "уменьшается внешнее плечо момента относительно позвоночника и таза", "меньше стабилизационная нагрузка на поясницу", technique),
            vector_effect("снаряд смещается вперед", "increases", ["hip", "lumbar_spine"], ["hamstrings", "spinal_erectors"], "возрастает момент сгибания бедра и позвоночника", "выше требование к задней цепи и разгибателям позвоночника", technique),
        ],
    )
    card["biomechanics"]["technique_variables"] = [
        make_technique_variable("knee_flexion", "сгибание колена", "Степень сгибания колена меняет длину хамстрингов и вклад квадрицепса.", "Меньшее сгибание колена обычно повышает растяжение хамстрингов; большее сгибание снижает hinge-акцент.", ["hip", "knee"], ["hamstrings", "vastus_lateralis", "lower_gluteus_maximus"], technique),
        make_technique_variable("bar_distance", "расстояние снаряда от тела", "Определяет плечо момента относительно бедра и позвоночника.", "Чем дальше снаряд от тела, тем выше требования к разгибателям бедра и позвоночника.", ["hip", "lumbar_spine"], ["hamstrings", "spinal_erectors"], technique),
        make_technique_variable("range_of_motion", "глубина опускания", "Определяется сохранением позиции позвоночника и доступной длиной задней поверхности бедра.", "Опускание ниже доступного контроля часто переводит движение в сгибание позвоночника.", ["hip", "lumbar_spine"], ["hamstrings", "spinal_erectors"], technique),
    ]
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Hinge-паттерн нагружает заднюю цепь через сгибание и разгибание бедра; при румынской тяге особенно важны эксцентрический контроль и растянутая позиция хамстрингов, а смещение снаряда вперед повышает требования к бедру и поясничной стабилизации.",
        biomech,
    )
    card["resistance_profile"] = {
        "profile_type": "ascending" if romanian else "variable",
        "peak_loading_region": "lengthened" if romanian else "bottom",
        "explanation": "В румынской тяге субъективно и механически важна нижняя растянутая часть; в классической тяге профиль зависит от старта, антропометрии и траектории снаряда.",
        "evidence_type": "biomechanical_inference",
        "confidence": confidence_from_sources(biomech)[0],
        "confidence_score": confidence_from_sources(biomech)[1],
        "assumptions": ["Свободный вес.", "Снаряд удерживается близко к телу.", "Позвоночник сохраняет нейтральную позицию."],
        "source_ids": biomech,
    }
    card["muscle_stimulus_phase_bias"] = [
        {"muscle_id": "hamstrings", "stimulus_region": "lengthened", "rationale": "Хамстринги работают при увеличенной длине в нижней части hinge-амплитуды.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
        {"muscle_id": "lower_gluteus_maximus", "stimulus_region": "lengthened", "rationale": "Ягодичные создают разгибание бедра из согнутого положения.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
    ]
    card["relative_muscle_emphasis"] = [
        relative_emphasis("hamstrings", 90 if romanian else 75, "Главный ограничивающий и целевой компонент hinge-паттерна.", biomech),
        relative_emphasis("lower_gluteus_maximus", 80, "Главный разгибатель бедра в подъеме.", biomech),
        relative_emphasis("spinal_erectors", 70 if not romanian else 60, "Высокая стабилизационная роль против сгибания позвоночника.", biomech),
    ]
    fill_common_practical_fields(card, source_ids=technique, profile="hinge")


def apply_bench_press_template(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    ctx = source_context(sources)
    text = card_search_text(card)
    equipment = infer_equipment_and_modality(text, default_load_placement="hands")
    biomech = ctx["biomech"]
    technique = ctx["technique"]
    card.update(
        {
            "exercise_family": "bench_press",
            "category": "upper_body_strength",
            "body_region": "upper_body",
            "target_region": "chest",
            "dominance_type": "horizontal_push",
            "modality": equipment["modality"],
            "equipment_required": equipment["equipment_required"] or ["bench"],
            "compound_type": "compound",
            "movement_patterns": ["horizontal_push"],
            "force_vector": "vertical",
            "kinetic_chain": "open_chain",
            "movement_planes": ["sagittal", "transverse"],
            "body_position": "supine",
            "limb_pattern": "bilateral",
            "technical_complexity": "moderate",
            "mobility_requirements": ["контроль положения лопаток", "достаточная горизонтальная абдукция плеча", "стабильный хват"],
            "contraction_phase_emphasis": "mixed",
            "stimulus_phase_bias": "lengthened",
        }
    )
    card["primary_muscles"] = [
        make_muscle_summary("mid_chest", "prime_mover", "lengthened", "Создает горизонтальное приведение плеча при жиме.", biomech),
        make_muscle_summary("upper_chest", "synergist", "mixed", "Вклад растет при более наклонной траектории/скамье.", biomech),
        make_muscle_summary("triceps_lateral_head", "synergist", "shortened", "Создает разгибание локтя в подъеме.", biomech),
        make_muscle_summary("triceps_medial_head", "synergist", "shortened", "Помогает разгибанию локтя.", biomech),
    ]
    card["secondary_muscles"] = [
        make_muscle_summary("front_deltoid", "synergist", "mixed", "Помогает сгибанию и горизонтальному приведению плеча.", biomech),
        make_muscle_summary("triceps_long_head", "synergist", "mixed", "Помогает разгибанию локтя, но его роль зависит от положения плеча.", biomech),
    ]
    card["stabilizers"] = [
        {**make_muscle_summary("rotator_cuff", "stabilizer", "mixed", "Центрирует плечевую кость и стабилизирует плечевой сустав.", technique), "stabilization_role": "glenohumeral_stability"},
        {**make_muscle_summary("serratus_anterior", "stabilizer", "mixed", "Помогает контролю лопатки.", technique), "stabilization_role": "scapular_control"},
        {**make_muscle_summary("lower_lats", "stabilizer", "mixed", "Помогает контролировать плечевой пояс и траекторию.", technique), "stabilization_role": "bar_path_control"},
    ]
    card["joint_actions"] = [
        make_joint_action_summary("glenohumeral", ["horizontal_adduction", "flexion"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("elbow", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("scapulothoracic", ["stabilization", "scapular_retraction"], ["setup", "eccentric_descent", "concentric_ascent"], technique),
    ]
    card["biomechanics"]["movement_phases"] = [
        make_phase("setup", "setup", "настройка", "isometric", "атлет лежит на скамье", "лопатки и хват зафиксированы", ["ретракция/депрессия лопаток", "устойчивые стопы", "выбор хвата"], technique),
        make_phase("eccentric_descent", "eccentric", "опускание", "eccentric", "локти разогнуты, снаряд над плечевым поясом", "снаряд у нижней/средней части груди", ["сгибание локтя", "горизонтальная абдукция плеча", "контроль лопаток"], biomech),
        make_phase("bottom_transition", "bottom_transition", "нижний переход", "isometric", "снаряд у груди", "начало подъема", ["сохранение позиции плеча", "контроль паузы/касания"], biomech),
        make_phase("concentric_ascent", "concentric", "жим вверх", "concentric", "снаряд у груди", "локти разогнуты", ["горизонтальное приведение плеча", "разгибание локтя"], biomech),
        make_phase("lockout", "lockout", "фиксация", "isometric", "локти разогнуты", "снаряд стабилен", ["контроль локтей и лопаток"], technique),
    ]
    card["biomechanics"]["joint_mechanics"] = [
        make_joint_mechanics("glenohumeral", "eccentric_descent", ["horizontal_abduction"], "moderate", "high", "грудные и передняя дельта контролируют опускание", "Ширина хвата и точка касания меняют плечевой момент.", biomech),
        make_joint_mechanics("elbow", "eccentric_descent", ["flexion"], "moderate", "moderate", "трицепс контролирует сгибание локтя", "Более узкий хват обычно повышает относительный вклад локтевого разгибания.", biomech),
        make_joint_mechanics("glenohumeral", "concentric_ascent", ["horizontal_adduction"], "moderate", "high", "грудные мышцы создают горизонтальное приведение плеча", "Плечо наиболее нагружено в нижней части при большем растяжении грудных.", biomech),
        make_joint_mechanics("elbow", "concentric_ascent", ["extension"], "moderate", "high", "трицепс разгибает локоть", "Требование к трицепсу возрастает ближе к верхней части и при узком хвате.", biomech),
    ]
    card["biomechanics"]["muscle_roles_by_phase"] = [
        make_muscle_role_by_phase("eccentric_descent", "mid_chest", "prime_mover", "эксцентрически контролирует горизонтальную абдукцию плеча", "shoulder_horizontal_abduction_control", "eccentric", "lengthening", "high", biomech),
        make_muscle_role_by_phase("eccentric_descent", "triceps_lateral_head", "synergist", "контролирует сгибание локтя", "elbow_flexion_control", "eccentric", "lengthening", "moderate", biomech),
        make_muscle_role_by_phase("concentric_ascent", "mid_chest", "prime_mover", "создает горизонтальное приведение плеча", "shoulder_horizontal_adduction", "concentric", "shortening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "triceps_lateral_head", "synergist", "создает разгибание локтя", "elbow_extension", "concentric", "shortening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "front_deltoid", "synergist", "помогает движению плеча вперед/вверх", "shoulder_flexion_assistance", "concentric", "shortening", "moderate", biomech),
    ]
    card["biomechanics"]["external_load_mechanics"] = base_external_load(
        equipment,
        technique,
        [
            moment_arm("glenohumeral", "снаряд находится ниже и дальше от плеча в нижней позиции", "увеличивается момент горизонтальной абдукции плеча", ["mid_chest", "front_deltoid"]),
            moment_arm("elbow", "локоть сильнее согнут или хват уже", "увеличивается требование к разгибателям локтя", ["triceps_lateral_head", "triceps_medial_head"]),
        ],
        [
            vector_effect("более широкий хват", "shifts", ["glenohumeral", "elbow"], ["mid_chest", "triceps_lateral_head"], "обычно увеличивает горизонтальную абдукцию плеча и снижает ROM локтя", "относительно больше грудной акцент и меньше локтевой ROM", technique),
            vector_effect("более узкий хват", "shifts", ["elbow", "glenohumeral"], ["triceps_lateral_head", "triceps_medial_head"], "увеличивает роль разгибания локтя", "относительно больше акцент на трицепс", technique),
        ],
    )
    card["biomechanics"]["technique_variables"] = [
        make_technique_variable("grip_width", "ширина хвата", "Меняет амплитуду плеча и локтя.", "Широкий хват чаще смещает акцент к грудным; узкий повышает вклад трицепса.", ["glenohumeral", "elbow"], ["mid_chest", "triceps_lateral_head"], technique),
        make_technique_variable("touch_point", "точка касания", "Меняет траекторию и плечевой момент.", "Слишком высокая точка касания может увеличивать стресс плеча.", ["glenohumeral"], ["mid_chest", "front_deltoid"], technique),
        make_technique_variable("scapular_position", "положение лопаток", "Определяет стабильность плечевого пояса.", "Потеря контроля лопаток снижает стабильность плеча.", ["scapulothoracic", "glenohumeral"], ["rotator_cuff", "serratus_anterior"], technique),
    ]
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Жим лежа сочетает горизонтальное приведение плеча и разгибание локтя; нижняя часть амплитуды сильнее нагружает грудные и плечевой сустав, а верхняя часть и узкий хват увеличивают относительную роль трицепса.",
        biomech,
    )
    card["resistance_profile"] = {
        "profile_type": "ascending",
        "peak_loading_region": "lengthened",
        "explanation": "Для свободного жима значимые требования часто возникают в нижней растянутой позиции грудных и в зоне смены направления.",
        "evidence_type": "biomechanical_inference",
        "confidence": confidence_from_sources(biomech)[0],
        "confidence_score": confidence_from_sources(biomech)[1],
        "assumptions": ["Свободный вес.", "Стандартный горизонтальный жим лежа."],
        "source_ids": biomech,
    }
    card["muscle_stimulus_phase_bias"] = [
        {"muscle_id": "mid_chest", "stimulus_region": "lengthened", "rationale": "Грудные растянуты в нижней позиции жима.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
        {"muscle_id": "triceps_lateral_head", "stimulus_region": "shortened", "rationale": "Трицепс особенно важен при разгибании локтя в подъеме.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech},
    ]
    card["relative_muscle_emphasis"] = [
        relative_emphasis("mid_chest", 90, "Главный двигатель горизонтального жима.", biomech),
        relative_emphasis("front_deltoid", 60, "Синергист плечевого движения.", biomech),
        relative_emphasis("triceps_lateral_head", 70, "Главный вклад в разгибание локтя.", biomech),
    ]
    fill_common_practical_fields(card, source_ids=technique, profile="bench_press")


def apply_hip_thrust_template(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    ctx = source_context(sources)
    text = card_search_text(card)
    equipment = infer_equipment_and_modality(text, default_load_placement="hips")
    biomech = ctx["biomech"]
    technique = ctx["technique"]
    card.update(
        {
            "exercise_family": "hip_thrust_bridge",
            "category": "lower_body_strength",
            "body_region": "lower_body",
            "target_region": "glutes",
            "dominance_type": "hip_dominant",
            "modality": equipment["modality"],
            "equipment_required": equipment["equipment_required"],
            "compound_type": "compound",
            "movement_patterns": ["hip_thrust_bridge"],
            "force_vector": "vertical",
            "kinetic_chain": "closed_chain",
            "movement_planes": ["sagittal"],
            "body_position": "supported",
            "limb_pattern": "bilateral",
            "technical_complexity": "moderate",
            "mobility_requirements": ["контроль таза", "достаточное разгибание бедра", "устойчивая позиция стоп"],
            "contraction_phase_emphasis": "mixed",
            "stimulus_phase_bias": "shortened",
        }
    )
    card["primary_muscles"] = [
        make_muscle_summary("lower_gluteus_maximus", "prime_mover", "shortened", "Создает разгибание бедра и пик сокращения в верхней позиции.", biomech),
        make_muscle_summary("upper_gluteus_maximus", "prime_mover", "shortened", "Помогает разгибанию бедра и заднему наклону таза.", biomech),
    ]
    card["secondary_muscles"] = [
        make_muscle_summary("hamstrings", "synergist", "mixed", "Помогают разгибанию бедра, но вклад зависит от угла колена.", biomech),
        make_muscle_summary("hip_adductors", "synergist", "mixed", "Помогают стабилизации и разгибанию бедра.", biomech),
    ]
    card["stabilizers"] = [
        {**make_muscle_summary("transverse_abdominis", "stabilizer", "mixed", "Помогает контролировать таз и поясницу.", technique), "stabilization_role": "pelvic_control"},
        {**make_muscle_summary("spinal_erectors", "stabilizer", "mixed", "Помогает удерживать корпус, но не должен доминировать через переразгибание поясницы.", technique), "stabilization_role": "trunk_control"},
    ]
    card["joint_actions"] = [
        make_joint_action_summary("hip", ["flexion", "extension"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("knee", ["stabilization"], ["eccentric_descent", "concentric_ascent"], biomech),
        make_joint_action_summary("lumbar_spine", ["anti_extension", "stabilization"], ["concentric_ascent", "top_position"], technique),
    ]
    card["biomechanics"]["movement_phases"] = [
        make_phase("setup", "setup", "настройка", "isometric", "верх спины опирается на скамью/пол", "стопы и нагрузка зафиксированы", ["позиция стоп", "брейсинг", "нагрузка над тазом"], technique),
        make_phase("eccentric_descent", "eccentric", "опускание таза", "eccentric", "бедро разогнуто", "таз опущен, бедро согнуто", ["контроль сгибания бедра", "сохранение позиции ребер и таза"], biomech),
        make_phase("concentric_ascent", "concentric", "подъем таза", "concentric", "бедро согнуто", "бедро разогнуто", ["разгибание бедра", "контроль колена и стопы"], biomech),
        make_phase("top_position", "peak_contraction", "верхняя фиксация", "isometric", "бедро разогнуто", "таз стабилен", ["пиковое сокращение ягодичных", "избегать переразгибания поясницы"], technique),
    ]
    card["biomechanics"]["joint_mechanics"] = [
        make_joint_mechanics("hip", "eccentric_descent", ["flexion"], "moderate", "high", "ягодичные контролируют сгибание бедра", "Нагрузка расположена близко к тазу, поэтому профиль отличается от hinge с нагрузкой в руках.", biomech),
        make_joint_mechanics("hip", "concentric_ascent", ["extension"], "moderate", "high", "ягодичные разгибают бедро", "Требования высоки ближе к верхней части, где достигается пиковое разгибание.", biomech),
        make_joint_mechanics("lumbar_spine", "top_position", ["anti_extension", "stabilization"], "near_isometric", "moderate", "кор стабилизирует таз и поясницу", "Переразгибание поясницы может маскировать недостаточное разгибание бедра.", technique),
    ]
    card["biomechanics"]["muscle_roles_by_phase"] = [
        make_muscle_role_by_phase("eccentric_descent", "lower_gluteus_maximus", "prime_mover", "контролирует сгибание бедра", "hip_flexion_control", "eccentric", "lengthening", "high", biomech),
        make_muscle_role_by_phase("concentric_ascent", "lower_gluteus_maximus", "prime_mover", "создает разгибание бедра", "hip_extension", "concentric", "shortening", "very_high", biomech),
        make_muscle_role_by_phase("top_position", "upper_gluteus_maximus", "prime_mover", "удерживает таз и бедро в разогнутой позиции", "hip_extension_hold", "isometric", "shortened", "high", biomech),
        make_muscle_role_by_phase("top_position", "transverse_abdominis", "stabilizer", "ограничивает переразгибание поясницы", "lumbar_anti_extension", "isometric", "near_isometric", "moderate", technique),
    ]
    card["biomechanics"]["external_load_mechanics"] = base_external_load(
        equipment,
        technique,
        [
            moment_arm("hip", "нагрузка расположена над тазом при согнутом бедре", "возникает требование к разгибанию бедра", ["lower_gluteus_maximus", "upper_gluteus_maximus"]),
            moment_arm("lumbar_spine", "ребра раскрываются и таз уходит в передний наклон", "часть движения может перейти в поясничное переразгибание", ["spinal_erectors", "transverse_abdominis"]),
        ],
        [
            vector_effect("стопы дальше от таза", "shifts", ["hip", "knee"], ["hamstrings", "lower_gluteus_maximus"], "увеличивается вклад задней поверхности бедра", "относительно больше участие хамстрингов", technique),
            vector_effect("стопы ближе к тазу", "shifts", ["knee", "hip"], ["vastus_lateralis", "lower_gluteus_maximus"], "возрастает сгибание колена и меняется угол бедра", "может увеличиться вклад квадрицепса/снизиться хамстринг-акцент", technique),
        ],
    )
    card["biomechanics"]["technique_variables"] = [
        make_technique_variable("foot_position", "позиция стоп", "Меняет углы колена и бедра.", "Дальняя позиция стоп повышает вклад хамстрингов; близкая меняет коленный угол и может снижать целевой ягодичный акцент.", ["hip", "knee"], ["hamstrings", "lower_gluteus_maximus"], technique),
        make_technique_variable("pelvic_control", "контроль таза", "Определяет, идет ли движение через бедро или поясницу.", "Задний наклон таза вверху помогает удержать движение в тазобедренном суставе.", ["hip", "lumbar_spine"], ["lower_gluteus_maximus", "transverse_abdominis"], technique),
    ]
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Hip thrust/bridge смещает основную механику к разгибанию бедра с высоким ягодичным вкладом и выраженной важностью верхней позиции; контроль таза нужен, чтобы не заменить разгибание бедра переразгибанием поясницы.",
        biomech,
    )
    card["resistance_profile"] = {
        "profile_type": "ascending",
        "peak_loading_region": "shortened",
        "explanation": "Пиковые требования часто ощущаются ближе к верхней позиции разгибания бедра.",
        "evidence_type": "biomechanical_inference",
        "confidence": confidence_from_sources(biomech)[0],
        "confidence_score": confidence_from_sources(biomech)[1],
        "assumptions": ["Нагрузка расположена на тазу.", "Стандартная техника без поясничного переразгибания."],
        "source_ids": biomech,
    }
    card["muscle_stimulus_phase_bias"] = [
        {"muscle_id": "lower_gluteus_maximus", "stimulus_region": "shortened", "rationale": "Высокие требования в верхней позиции разгибания бедра.", "evidence_type": "biomechanical_inference", "confidence": confidence_from_sources(biomech)[0], "source_ids": biomech}
    ]
    card["relative_muscle_emphasis"] = [
        relative_emphasis("lower_gluteus_maximus", 95, "Главный двигатель разгибания бедра.", biomech),
        relative_emphasis("upper_gluteus_maximus", 85, "Сильный вклад в верхней позиции и контроль таза.", biomech),
        relative_emphasis("hamstrings", 45, "Синергист, вклад зависит от позиции стоп.", biomech),
    ]
    fill_common_practical_fields(card, source_ids=technique, profile="hip_thrust")


def apply_split_squat_template(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    apply_squat_template(card, sources)
    ctx = source_context(sources)
    source_ids = ctx["biomech"]
    card.update(
        {
            "exercise_family": "split_squat_lunge",
            "movement_patterns": ["split_squat", "lunge"],
            "limb_pattern": "unilateral",
            "target_region": "quadriceps",
            "technical_complexity": "moderate",
            "mobility_requirements": [
                "контроль таза во фронтальной плоскости",
                "достаточная подвижность сгибателей бедра задней ноги",
                "баланс в разножке",
            ],
        }
    )
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Split squat/lunge сохраняет механику приседания, но добавляет односторонний контроль таза, фронтальную стабильность и большую зависимость мышечного акцента от длины шага и наклона корпуса.",
        source_ids,
    )
    card["biomechanics"]["technique_variables"].append(
        make_technique_variable("step_length", "длина шага", "Меняет углы бедра и колена передней ноги.", "Короткий шаг чаще повышает коленный момент; длинный шаг смещает акцент к бедру и ягодичным.", ["hip", "knee"], ["vastus_lateralis", "lower_gluteus_maximus"], source_ids)
    )


def relative_emphasis(muscle_id: str, score: int, rationale: str, source_ids: list[str]) -> dict[str, Any]:
    confidence, confidence_score = confidence_from_sources(source_ids)
    return {
        "muscle_id": muscle_id,
        "relative_emphasis_score": score,
        "score_type": "evidence_informed_estimate",
        "confidence": confidence,
        "confidence_score": confidence_score,
        "rationale": rationale,
        "source_ids": source_ids,
    }


def fill_common_practical_fields(card: dict[str, Any], source_ids: list[str], profile: str) -> None:
    fatigue_profiles = {
        "squat": ("high", "high", "high", "high", "high"),
        "hinge": ("high", "high", "high", "high", "moderate"),
        "bench_press": ("moderate", "moderate", "moderate", "moderate", "moderate"),
        "hip_thrust": ("moderate", "moderate", "moderate", "moderate", "moderate"),
    }
    local, systemic, technical, axial, stability = fatigue_profiles.get(profile, ("unclear", "unclear", "unclear", "unclear", "unclear"))
    confidence, score = confidence_from_sources(source_ids)
    card["fatigue_cost"] = {
        "local_fatigue": local,
        "systemic_fatigue": systemic,
        "technical_fatigue": technical,
        "axial_loading": axial,
        "stability_demand": stability,
        "overall_fatigue_cost": systemic,
        "evidence_type": "expert_inference",
        "confidence": confidence,
        "confidence_score": score,
        "assumptions": ["Оценка зависит от нагрузки, объема, близости к отказу и техники."],
        "source_ids": source_ids,
    }
    card["sfr"] = {
        "sfr_class": "context_dependent",
        "evidence_type": "expert_inference",
        "confidence": confidence,
        "confidence_score": score,
        "context": "Stimulus-to-fatigue ratio зависит от цели, техники, индивидуальной антропометрии и дозировки нагрузки.",
        "assumptions": ["SFR не является прямым лабораторным показателем и трактуется как практическая эвристика."],
        "source_ids": source_ids,
    }
    if profile == "bench_press":
        card["common_errors"] = [
            make_common_error("потеря позиции лопаток", "снижается стабильность плечевого сустава и меняется траектория", "зафиксировать лопатки и повторить настройку", "moderate", source_ids),
            make_common_error("слишком высокая точка касания", "может увеличить плечевой момент и дискомфорт", "держать траекторию в зоне, соответствующей хвату и антропометрии", "context_dependent", source_ids),
            make_common_error("ранний отрыв таза", "меняет механику и снижает воспроизводимость повторения", "снизить нагрузку и удерживать стабильную опору", "moderate", source_ids),
        ]
        card["execution_steps"] = {
            "setup": ["лечь на скамью", "зафиксировать лопатки", "выбрать устойчивый хват и опору стоп"],
            "execution": ["контролируемо опустить снаряд", "сохранить позицию плеч", "выжать снаряд вверх по стабильной траектории"],
            "rom": ["опускать до контролируемой нижней позиции без потери плечевой стабильности"],
            "breathing_bracing": ["вдох и брейсинг перед опусканием", "сохранять жесткость корпуса в повторении"],
            "tempo_control": ["контролируемая эксцентрика", "без отскока от груди"],
        }
    elif profile == "hip_thrust":
        card["common_errors"] = [
            make_common_error("переразгибание поясницы вверху", "движение смещается из тазобедренного сустава в поясницу", "держать ребра и таз под контролем", "moderate", source_ids),
            make_common_error("неудачная позиция стоп", "меняется вклад хамстрингов, квадрицепса и ягодичных", "подобрать позицию стоп под стабильное разгибание бедра", "context_dependent", source_ids),
            make_common_error("неконтролируемое опускание", "снижается контроль нижней позиции и воспроизводимость амплитуды", "замедлить эксцентрику", "low", source_ids),
        ]
        card["execution_steps"] = {
            "setup": ["расположить верх спины на опоре", "зафиксировать стопы", "разместить нагрузку над тазом"],
            "execution": ["поднять таз через разгибание бедра", "удержать верхнюю позицию", "контролируемо опустить таз"],
            "rom": ["работать в амплитуде, где движение остается в бедре, а не в пояснице"],
            "breathing_bracing": ["сохранять брейсинг и контроль ребер"],
            "tempo_control": ["контролируемое опускание", "короткая фиксация вверху при необходимости"],
        }
    elif profile == "hinge":
        card["common_errors"] = [
            make_common_error("снаряд уходит далеко от тела", "увеличивается плечо момента для бедра и позвоночника", "вести снаряд близко к ногам", "moderate", source_ids),
            make_common_error("сгибание позвоночника вместо сгибания бедра", "нагрузка смещается с тазобедренного шарнира на позвоночник", "снизить амплитуду до контролируемой позиции", "high", source_ids),
            make_common_error("чрезмерное сгибание коленей в румынской тяге", "снижается растяжение хамстрингов и меняется паттерн", "сохранять мягкое, но стабильное сгибание колена", "context_dependent", source_ids),
        ]
        card["execution_steps"] = {
            "setup": ["встать с нагрузкой в руках", "зафиксировать корпус", "держать снаряд близко к телу"],
            "execution": ["отвести таз назад", "контролировать опускание", "разогнуть бедро для подъема"],
            "rom": ["останавливаться до потери нейтрального положения позвоночника"],
            "breathing_bracing": ["вдох и брейсинг перед опусканием", "сохранять жесткость корпуса"],
            "tempo_control": ["медленная контролируемая эксцентрика", "без рывка в нижней позиции"],
        }
    else:
        card["common_errors"] = [
            make_common_error("потеря контроля корпуса", "меняется распределение момента между суставами", "снизить нагрузку и стабилизировать корпус", "moderate", source_ids),
            make_common_error("неконтролируемая нижняя позиция", "снижается воспроизводимость техники", "замедлить эксцентрику и держать активный контроль", "moderate", source_ids),
            make_common_error("смещение коленей без контроля", "может менять нагрузку на колено и бедро", "подобрать стойку и траекторию под антропометрию", "context_dependent", source_ids),
        ]
        card["execution_steps"] = {
            "setup": ["выбрать стойку", "зафиксировать корпус", "подготовить снаряд"],
            "execution": ["контролируемо опуститься", "сохранить траекторию", "подняться без потери позиции"],
            "rom": ["использовать контролируемую амплитуду"],
            "breathing_bracing": ["вдох и брейсинг перед повторением"],
            "tempo_control": ["контролируемая эксцентрика", "стабильный подъем"],
        }

    card["best_use"] = {
        "hypertrophy": "подходит при технике, позволяющей целевым мышцам получать стабильную нагрузку",
        "strength": "подходит при прогрессии нагрузки и контроле техники",
        "skill": "требует повторяемой траектории и дозировки усталости",
    }
    card["typical_rep_ranges"] = ["3-6 для силы", "6-12 для силы/гипертрофии", "8-15+ для гипертрофии и техники при умеренной нагрузке"]
    card["progression_options"] = ["увеличение нагрузки", "увеличение повторений", "увеличение подходов", "контроль темпа", "пауза в ключевой позиции"]
    card["when_to_avoid_or_modify"] = ["боль или выраженный дискомфорт в рабочем суставе", "невозможность удерживать контролируемую технику", "усталость, резко меняющая механику движения"]
    card["prerequisite_skill_mobility"] = card.get("mobility_requirements", [])
    card["supersets_trisets"] = [
        {
            "format": "paired_set",
            "combination": ["низко конфликтующее упражнение на другую мышечную группу"],
            "logic": "снизить локальное пересечение усталости",
            "fatigue_warning": "не сочетать с упражнением, которое ухудшает контроль ключевой техники",
        }
    ]
    card["variations"] = [
        {
            "name": "вариация с изменением оборудования",
            "primary_emphasis": "меняет профиль сопротивления и требования к стабилизации",
            "mechanical_difference": "зависит от линии силы и точки приложения нагрузки",
            "when_to_choose": "когда нужна другая нагрузка на суставы или целевые мышцы",
            "evidence_type": "expert_inference",
            "confidence": confidence,
        }
    ]
    card["alternatives"] = [
        {
            "name": "упражнение того же паттерна движения",
            "similarity": "сохраняет основной суставной паттерн",
            "main_difference": "отличается оборудованием, стабильностью или профилем сопротивления",
            "when_to_choose": "если текущая вариация плохо подходит по технике, оборудованию или переносимости",
        }
    ]
    card["safety"] = {
        "general": "Не является медицинской рекомендацией. При боли, травме или реабилитационном контексте нужна индивидуальная оценка специалиста.",
        "load_management": "Увеличивать нагрузку только при сохранении повторяемой техники.",
        "fatigue_management": "Останавливать подход, если усталость резко меняет механику движения.",
    }


def apply_unknown_template(card: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    ctx = source_context(sources)
    source_ids = ctx["all"]
    card["biomechanics"]["biomechanical_summary"] = make_claim(
        "Для этого упражнения пока нет локального шаблона биомеханического заполнения; источники сохранены, но поля требуют ручного или следующего автоматического разбора.",
        source_ids,
        evidence_type="insufficient_evidence",
        confidence="low",
        confidence_score=25,
    )
    card["limitations"].append("Для упражнения не найден локальный movement template; карточка оставлена как staged_draft с source ledger.")
    card["not_supported_claims"].append("Автоматический разбор мышц по фазам не выполнен без подходящего шаблона.")


def refresh_evidence_summary(card: dict[str, Any], sources: list[dict[str, Any]], template_id: str) -> None:
    backends = sorted({backend for source in sources for backend in source.get("source_backends", [])})
    card["evidence_summary"] = {
        "source_count": len(sources),
        "direct_match_count": sum(1 for source in sources if source.get("exercise_match") == "direct"),
        "fulltext_count": sum(1 for source in sources if source.get("has_fulltext")),
        "retracted_count": sum(1 for source in sources if source.get("is_retracted")),
        "backends": backends,
        "template_id": template_id,
        "population_method": "controlled_template_with_source_ids",
        "important_caveat": "Большинство биомеханических полей являются структурированной inference-моделью на основе паттерна упражнения и найденных источников; точные утверждения из full text требуют отдельного extraction этапа.",
    }


def refresh_evidence_ledger(card: dict[str, Any]) -> None:
    claims = []
    for claim in card.get("movement_pattern_details", []):
        claims.append(claim)
    summary = card.get("biomechanics", {}).get("biomechanical_summary")
    if summary:
        claims.append(summary)
    claims.append(
        make_claim(
            "Мышечные роли по фазам заполнены как biomechanical_inference на основе movement-template и source ledger.",
            card.get("biomechanics", {}).get("biomechanical_summary", {}).get("source_ids", []),
            evidence_type="biomechanical_inference",
        )
    )
    card["evidence_ledger"] = claims


def populate_card(card: dict[str, Any], source_ledger: dict[str, Any]) -> dict[str, Any]:
    populated = copy.deepcopy(card)
    sources = source_ledger.get("sources") or []
    template_id = match_template(populated)

    source_ids = direct_source_ids(sources)
    populated["movement_pattern_details"] = [
        make_claim(
            f"Упражнение сопоставлено с локальным movement template: {template_id}.",
            source_ids,
            evidence_type="expert_inference" if template_id != "unknown" else "insufficient_evidence",
        )
    ]

    if template_id == "squat":
        apply_squat_template(populated, sources)
    elif template_id == "split_squat":
        apply_split_squat_template(populated, sources)
    elif template_id == "romanian_deadlift":
        apply_hinge_template(populated, sources, romanian=True)
    elif template_id == "deadlift":
        apply_hinge_template(populated, sources, romanian=False)
    elif template_id == "bench_press":
        apply_bench_press_template(populated, sources)
    elif template_id == "hip_thrust":
        apply_hip_thrust_template(populated, sources)
    else:
        apply_unknown_template(populated, sources)

    if template_id != "unknown":
        populated["assumptions"] = unique_strings(
            [
                *populated.get("assumptions", []),
                "Карточка заполнена контролируемым биомеханическим шаблоном.",
                "Source IDs указывают на найденные источники, но не означают дословное извлечение каждого утверждения из full text.",
            ]
        )
        populated["limitations"] = unique_strings(
            [
                *populated.get("limitations", []),
                "Точная величина мышечной активности, суставных моментов и нагрузки зависит от техники, антропометрии, оборудования и нагрузки.",
                "EMG-данные, если присутствуют среди источников, не интерпретируются напрямую как гипертрофический стимул.",
            ]
        )
        populated["not_supported_claims"] = unique_strings(
            [
                *populated.get("not_supported_claims", []),
                "Карточка не утверждает точные проценты вклада мышц без прямых источников.",
                "Карточка не является медицинской или реабилитационной рекомендацией.",
            ]
        )

    refresh_evidence_summary(populated, sources, template_id)
    refresh_evidence_ledger(populated)
    populated["metadata"]["populated_at"] = now_iso()
    populated["metadata"]["population_method"] = "controlled_template_with_source_ids"
    populated["metadata"]["population_template_id"] = template_id
    populated["status"] = "staged_draft"
    return populated


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


def process_one(card_path: Path, sources_path: Path, output_path: Path | None, validate: bool) -> Path:
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
    parser = argparse.ArgumentParser(description="Populate staged exercise cards with biomechanical content.")
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

