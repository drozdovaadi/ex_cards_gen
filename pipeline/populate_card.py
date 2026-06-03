#!/usr/bin/env python
"""
Populate staged exercise cards from source evidence and movement decomposition.

This production fill step keeps the existing card schema unchanged. It fills
the current fields from direct sources when available; otherwise it writes
clearly marked biomechanical or expert inference from decomposed movement
components and records the caveat in limitations / not_supported_claims.
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
from movement_decomposition import build_movement_decomposition, decomposition_summary, load_decomposition


MUSCLE_TAXONOMY_PATH = PROJECT_ROOT / "schemas" / "taxonomies" / "muscles.json"


class PopulateError(RuntimeError):
    pass


@dataclass(frozen=True)
class MuscleInfo:
    muscle_id: str
    name_ru: str
    group_id: str


@dataclass(frozen=True)
class ComponentRule:
    component_ids: tuple[str, ...]
    family_ru: str
    category_ru: str
    body_region: str
    target_region: str
    dominance_type: str
    compound_type: str
    force_vector: str
    kinetic_chain: str
    movement_planes: tuple[str, ...]
    body_position: str
    limb_pattern: str
    technical_complexity: str
    primary_muscles: tuple[str, ...]
    secondary_muscles: tuple[str, ...]
    stabilizers: tuple[str, ...]
    joint_actions: tuple[tuple[str, tuple[str, ...]], ...]
    stimulus_phase_bias: str
    contraction_phase_emphasis: str
    resistance_profile_type: str
    peak_loading_region: str
    local_fatigue: str
    systemic_fatigue: str
    technical_fatigue: str
    axial_loading: str
    stability_demand: str
    overall_fatigue_cost: str
    sfr_class: str
    variations: tuple[tuple[str, str, str, str], ...]
    alternatives: tuple[tuple[str, str, str, str], ...]
    supersets: tuple[tuple[str, tuple[str, ...], str, str], ...]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_text(value: Any) -> str:
    value = str(value or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", value).strip()


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        item = re.sub(r"\s+", " ", str(value)).strip()
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


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


DISPLAY_DOMINANCE = {
    "hip_dominant": "Тазобедренная доминанта",
    "knee_dominant": "Коленная доминанта",
    "ankle_dominant": "Голеностопная доминанта",
    "horizontal_push": "Горизонтальное жимовое",
    "vertical_push": "Вертикальное жимовое",
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

DISPLAY_LOAD_PHASE = {
    "lengthened": "Растянутая",
    "mid_range": "Средняя амплитуда",
    "shortened": "Сокращенная",
    "mixed": "Смешанная",
    "unclear": "Не определена",
}

DISPLAY_CONTRACTION = {
    "concentric": "Концентрическая",
    "eccentric": "Эксцентрическая",
    "isometric": "Изометрическая",
    "quasi_isometric": "Квазиизометрическая",
    "stretch_shortening_cycle": "Цикл растяжения-сокращения",
    "mixed": "Смешанная",
    "unclear": "Не определен",
}


RULES: list[ComponentRule] = [
    ComponentRule(
        component_ids=("hip_hinge", "hip_extension_isolation"),
        family_ru="наклон через тазобедренный сустав",
        category_ru="силовое упражнение на заднюю цепь",
        body_region="lower_body",
        target_region="hamstrings",
        dominance_type="hip_dominant",
        compound_type="compound",
        force_vector="vertical",
        kinetic_chain="closed_chain",
        movement_planes=("sagittal",),
        body_position="standing",
        limb_pattern="bilateral",
        technical_complexity="moderate",
        primary_muscles=("hamstrings", "lower_gluteus_maximus", "upper_gluteus_maximus"),
        secondary_muscles=("spinal_erectors", "hip_adductors"),
        stabilizers=("transverse_abdominis", "obliques", "forearm_grip"),
        joint_actions=(("hip", ("flexion", "extension")), ("knee", ("stabilization",)), ("lumbar_spine", ("anti_flexion",))),
        stimulus_phase_bias="lengthened",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="descending",
        peak_loading_region="lengthened",
        local_fatigue="moderate",
        systemic_fatigue="moderate",
        technical_fatigue="moderate",
        axial_loading="moderate",
        stability_demand="moderate",
        overall_fatigue_cost="moderate",
        sfr_class="balanced",
        variations=(
            ("Румынская тяга с гантелями", "задняя поверхность бедра и ягодичные", "две опоры ног снижают требование к равновесию и позволяют взять больше вес", "когда нужно сохранить паттерн наклона через тазобедренный сустав, но убрать одноопорную сложность"),
            ("Румынская тяга на одной ноге без веса", "контроль таза и баланс", "убирает внешнюю нагрузку, оставляя двигательную задачу", "когда техника разваливается из-за гантели или усталости хвата"),
            ("B-stance Romanian deadlift", "задняя цепь с частичной разгрузкой второй ногой", "задняя нога страхует баланс, но основная нагрузка остается на передней ноге", "когда одноопорный вариант пока слишком нестабилен"),
            ("Разгибание спины на скамье", "ягодичные и разгибатели спины", "корпус движется относительно фиксированных ног и меньше зависит от хвата", "когда нужна похожая работа задней цепи без удержания гантели"),
        ),
        alternatives=(
            ("Hip thrust", "нагружает разгибание бедра", "пик нагрузки смещается ближе к верхней позиции и меньше растягивает заднюю поверхность бедра", "когда нужен больший акцент на ягодичные при меньшем требовании к наклону корпуса"),
            ("Сгибание ног лежа", "тренирует заднюю поверхность бедра", "работа идет через сгибание колена, а не через разгибание бедра", "когда нужно локально нагрузить хамстринги без осевой и балансной цены"),
            ("Классическая румынская тяга со штангой", "сохраняет тазобедренный паттерн", "двусторонняя опора и штанга дают выше абсолютную нагрузку", "когда приоритетом является силовая прогрессия, а не контроль одной стороны"),
            ("Тяга блока между ног", "тренирует разгибание бедра", "линия силы идет от блока и меняет момент в нижней и средней амплитуде", "когда нужна нагрузка на тазобедренное разгибание с меньшей ролью хвата"),
        ),
        supersets=(
            ("суперсет", ("Румынская тяга на одной ноге", "Pallof press"), "Добавляет контроль корпуса после тазобедренного наклона без прямого добивания тех же мышц.", "Сначала падает качество равновесия; снижайте вес, если таз начинает вращаться неконтролируемо."),
            ("трисет", ("Румынская тяга с гантелями", "Ягодичный мост", "Сгибание ног лежа"), "Комбинирует разгибание бедра, сокращенную позицию ягодичных и сгибание колена для задней цепи.", "Не ставьте трисет перед тяжелой тягой: локальная усталость задней поверхности бедра ухудшит контроль корпуса."),
        ),
    ),
    ComponentRule(
        component_ids=("open_hip_rotation", "hip_abduction"),
        family_ru="контроль отведения бедра и раскрытия таза",
        category_ru="силовое и координационное упражнение для тазобедренной области",
        body_region="lower_body",
        target_region="glutes",
        dominance_type="hip_dominant",
        compound_type="hybrid",
        force_vector="mixed",
        kinetic_chain="mixed",
        movement_planes=("frontal", "transverse"),
        body_position="standing",
        limb_pattern="unilateral",
        technical_complexity="high",
        primary_muscles=("gluteus_medius", "upper_gluteus_maximus"),
        secondary_muscles=("lower_gluteus_maximus", "obliques"),
        stabilizers=("transverse_abdominis", "spinal_erectors", "tibialis_anterior"),
        joint_actions=(("hip", ("abduction", "external_rotation", "stabilization")), ("lumbar_spine", ("anti_rotation",))),
        stimulus_phase_bias="shortened",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="variable",
        peak_loading_region="top",
        local_fatigue="moderate",
        systemic_fatigue="low",
        technical_fatigue="high",
        axial_loading="low",
        stability_demand="high",
        overall_fatigue_cost="moderate",
        sfr_class="context_dependent",
        variations=(
            ("Hip airplane без веса", "контроль таза и внешняя ротация бедра", "убирает силовой компонент удержания груза", "когда цель - моторный контроль, а не силовая нагрузка"),
            ("Hip airplane с опорой рукой", "контроль раскрытия таза с меньшим риском потери баланса", "свободная рука снижает требование к стопе и корпусу", "когда нужно обучить траекторию раскрытия таза"),
            ("Отведение бедра в кроссовере", "средняя ягодичная", "движение становится более локальным и менее одноопорным", "когда нужен мышечный акцент без сложной координации"),
            ("Боковая планка с отведением бедра", "средняя ягодичная и боковая линия корпуса", "добавляет удержание корпуса от бокового сгибания", "когда нужен контроль таза без наклона через тазобедренный сустав"),
        ),
        alternatives=(
            ("Pallof press", "тренирует контроль вращения корпуса", "нагрузка идет через трос, а не через одноопорный тазобедренный контроль", "когда ротация таза пока слишком сложна"),
            ("Отведение бедра сидя в тренажере", "нагружает отводящие мышцы бедра", "тренажер фиксирует корпус и снижает требование к равновесию", "когда нужен локальный объем для средней ягодичной"),
            ("Болгарский сплит-присед", "развивает одноопорную силу", "движение более коленно-доминантное и меньше требует раскрытия таза", "когда нужна силовая работа ноги без ротационного компонента"),
            ("Кабельная ротация корпуса", "сохраняет поперечную плоскость", "основная задача переносится с опорного бедра на корпус и плечевой пояс", "когда нужна ротационная нагрузка без наклона на одной ноге"),
        ),
        supersets=(
            ("суперсет", ("Hip airplane с опорой", "Отведение бедра в кроссовере"), "Сначала отрабатывается контроль таза, затем добирается локальная работа средней ягодичной.", "Если после первого упражнения таз дрожит, уменьшайте амплитуду отведения в кроссовере."),
            ("трисет", ("Румынская тяга на одной ноге", "Hip airplane", "Боковая планка"), "Связывает заднюю цепь, раскрытие таза и боковую стабилизацию корпуса.", "Высокая координационная усталость быстро портит технику; используйте умеренные повторы."),
        ),
    ),
    ComponentRule(
        component_ids=("trunk_pelvis_rotation_control", "diagonal_trunk_rotation"),
        family_ru="ротация и контроль корпуса",
        category_ru="упражнение для корпуса в поперечной плоскости",
        body_region="core",
        target_region="core",
        dominance_type="trunk_dominant",
        compound_type="hybrid",
        force_vector="rotational",
        kinetic_chain="mixed",
        movement_planes=("transverse", "multiplanar"),
        body_position="standing",
        limb_pattern="asymmetrical",
        technical_complexity="moderate",
        primary_muscles=("obliques", "transverse_abdominis"),
        secondary_muscles=("rectus_abdominis", "gluteus_medius", "spinal_erectors"),
        stabilizers=("serratus_anterior", "rotator_cuff", "forearm_grip"),
        joint_actions=(("thoracic_spine", ("internal_rotation", "external_rotation")), ("lumbar_spine", ("anti_rotation",)), ("hip", ("stabilization",))),
        stimulus_phase_bias="mixed",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="variable",
        peak_loading_region="transition",
        local_fatigue="moderate",
        systemic_fatigue="low",
        technical_fatigue="moderate",
        axial_loading="low",
        stability_demand="moderate",
        overall_fatigue_cost="moderate",
        sfr_class="context_dependent",
        variations=(
            ("Cable woodchopper сверху вниз", "косые мышцы и диагональная линия корпуса", "трос задает диагональную линию силы и делает момент зависимым от угла корпуса", "когда нужен управляемый ротационный стимул"),
            ("Cable lift снизу вверх", "ротация корпуса снизу вверх", "меняется направление диагонали и участие плечевого пояса", "когда нужна противоположная диагональ"),
            ("Pallof press", "анти-ротация", "движение становится почти изометрическим", "когда нужно снизить скорость и обучить контроль корпуса"),
            ("Медбол-бросок в стену с ротацией", "мощность в поперечной плоскости", "добавляет скорость и выпуск снаряда", "когда техника уже стабильна и нужна взрывная работа"),
        ),
        alternatives=(
            ("Боковая планка", "тренирует боковую линию корпуса", "меньше вращения, больше удержания от бокового сгибания", "когда ротация вызывает дискомфорт в пояснице"),
            ("Dead bug с резинкой", "нагружает контроль корпуса", "упражнение выполняется лежа и снижает нагрузку на тазобедренные суставы", "когда стоячие варианты слишком сложны"),
            ("Тяга троса одной рукой стоя", "требует анти-ротации", "основное движение становится тягой плеча, а корпус стабилизирует", "когда нужно совместить спину и контроль корпуса"),
            ("Landmine rotation", "работает в диагональной траектории", "дуга фиксирована грифом, а нагрузка больше зависит от плечевого рычага", "когда нужен более тяжелый ротационный вариант"),
        ),
        supersets=(
            ("суперсет", ("Cable woodchopper", "Pallof press"), "Сочетает динамическую ротацию и статический контроль того же направления.", "Не доводите первый подход до отказа: во втором упражнении корпус начнет разворачиваться за тросом."),
            ("трисет", ("Тяга троса одной рукой", "Cable woodchopper", "Боковая планка"), "Связывает тягу, вращение и боковую стабилизацию.", "Усталость хвата и плеча может ограничить качество корпуса раньше целевых мышц."),
        ),
    ),
    ComponentRule(
        component_ids=("horizontal_pull",),
        family_ru="горизонтальная тяга",
        category_ru="тяговое упражнение для спины",
        body_region="upper_body",
        target_region="back",
        dominance_type="horizontal_pull",
        compound_type="compound",
        force_vector="horizontal",
        kinetic_chain="open_chain",
        movement_planes=("sagittal",),
        body_position="seated",
        limb_pattern="bilateral",
        technical_complexity="moderate",
        primary_muscles=("rhomboids", "lower_trapezius", "lower_lats", "upper_lats"),
        secondary_muscles=("rear_deltoid", "teres_major", "biceps_brachii", "brachialis"),
        stabilizers=("spinal_erectors", "transverse_abdominis", "forearm_grip"),
        joint_actions=(("glenohumeral", ("extension", "horizontal_abduction")), ("scapulothoracic", ("scapular_retraction", "scapular_depression")), ("elbow", ("flexion",))),
        stimulus_phase_bias="shortened",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="variable",
        peak_loading_region="shortened",
        local_fatigue="moderate",
        systemic_fatigue="low",
        technical_fatigue="moderate",
        axial_loading="low",
        stability_demand="moderate",
        overall_fatigue_cost="moderate",
        sfr_class="balanced",
        variations=(
            ("Тяга сидя в кроссовере", "средняя часть спины и широчайшие", "трос дает постоянную линию тяги к корпусу", "когда нужна предсказуемая нагрузка и контроль лопаток"),
            ("Тяга гантели одной рукой", "широчайшие и контроль корпуса", "односторонняя нагрузка добавляет анти-ротационный спрос", "когда нужно выровнять стороны"),
            ("Тяга грудью к скамье", "спина с меньшей нагрузкой на поясницу", "опора груди убирает часть стабилизации корпуса", "когда поясница устала после тяг или приседаний"),
            ("Тяга штанги в наклоне", "спина и задняя цепь", "выше осевая и постуральная цена", "когда нужен более силовой вариант"),
        ),
        alternatives=(
            ("Вертикальная тяга", "нагружает широчайшие", "плечо движется сверху вниз, а не назад к корпусу", "когда нужен больший акцент на ширину спины"),
            ("Пуловер в тренажере", "нагружает разгибание плеча", "локоть почти не сгибается и меньше помогает бицепс", "когда нужно снизить вклад рук"),
            ("Face pull", "работает задняя дельтовидная и наружные ротаторы", "тяга идет выше и больше нагружает плечевой пояс", "когда нужна гигиена плеча и верх спины"),
            ("Тяга верхнего блока узким хватом", "сохраняет тяговый паттерн", "траектория становится вертикальнее", "когда горизонтальная тяга неудобна по оборудованию"),
        ),
        supersets=(
            ("суперсет", ("Тяга сидя", "Face pull"), "Сначала выполняется тяжелая тяга, затем добирается задняя дельтовидная и контроль лопаток.", "Не превращайте face pull в рывок после утомления хвата."),
            ("трисет", ("Тяга грудью к скамье", "Пуловер в тренажере", "Сгибание рук с гантелями"), "Разделяет спину, разгибание плеча и сгибатели локтя.", "Бицепс быстро устанет и может ограничить последующие тяги."),
        ),
    ),
    ComponentRule(
        component_ids=("vertical_pull", "shoulder_extension_pull"),
        family_ru="вертикальная тяга и разгибание плеча",
        category_ru="тяговое упражнение для широчайших мышц",
        body_region="upper_body",
        target_region="back",
        dominance_type="vertical_pull",
        compound_type="compound",
        force_vector="vertical",
        kinetic_chain="open_chain",
        movement_planes=("sagittal", "frontal"),
        body_position="seated",
        limb_pattern="bilateral",
        technical_complexity="moderate",
        primary_muscles=("lower_lats", "upper_lats", "teres_major"),
        secondary_muscles=("lower_trapezius", "rhomboids", "biceps_brachii", "brachialis"),
        stabilizers=("rotator_cuff", "transverse_abdominis", "forearm_grip"),
        joint_actions=(("glenohumeral", ("adduction", "extension")), ("scapulothoracic", ("scapular_depression", "scapular_downward_rotation")), ("elbow", ("flexion", "stabilization"))),
        stimulus_phase_bias="lengthened",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="variable",
        peak_loading_region="lengthened",
        local_fatigue="moderate",
        systemic_fatigue="low",
        technical_fatigue="moderate",
        axial_loading="low",
        stability_demand="moderate",
        overall_fatigue_cost="moderate",
        sfr_class="balanced",
        variations=(
            ("Тяга верхнего блока широким хватом", "широчайшие и большая круглая", "локти идут через отведение плеча", "когда нужен акцент на вертикальную тягу"),
            ("Подтягивание", "вертикальная тяга с весом тела", "закрытая цепь и выше требование к стабилизации лопаток", "когда достаточно силы для полного контроля амплитуды"),
            ("Тяга верхнего блока нейтральным хватом", "широчайшие и сгибатели локтя", "локти ближе к корпусу, часто проще удерживать плечи", "когда широкий хват раздражает плечи"),
            ("Тяга прямыми руками", "разгибание плеча и широчайшие", "локоть почти не сгибается, вклад бицепса ниже", "когда нужно изолировать движение плеча"),
        ),
        alternatives=(
            ("Горизонтальная тяга сидя", "тренирует спину тяговым движением", "акцент смещается к приведению лопаток и средней спине", "когда нужна толщина спины и меньше работа над головой"),
            ("Пуловер с гантелью", "нагружает разгибание плеча", "сопротивление зависит от гравитации и дуги плеча", "когда нет кроссовера или тренажера"),
            ("Тяга гантели одной рукой", "сохраняет работу широчайших", "односторонняя траектория добавляет контроль корпуса", "когда нужно выровнять стороны"),
            ("Face pull", "работает верх спины", "меньше широчайших и больше задней дельтовидной", "когда нужен плечевой баланс"),
        ),
        supersets=(
            ("суперсет", ("Тяга верхнего блока", "Пуловер на блоке"), "Сначала используется тяжелая вертикальная тяга, затем добирается разгибание плеча с меньшим вкладом бицепса.", "Если локти сгибаются в пуловере, снижайте вес: уставший бицепс забирает движение."),
            ("трисет", ("Подтягивание", "Тяга сидя", "Face pull"), "Комбинирует вертикальную тягу, горизонтальную тягу и контроль плечевого пояса.", "Высокая усталость хвата может раньше остановить сет, чем мышцы спины."),
        ),
    ),
]


def default_rule() -> ComponentRule:
    return ComponentRule(
        component_ids=("unmapped_resistance_exercise",),
        family_ru="неуточненное силовое упражнение",
        category_ru="силовое упражнение",
        body_region="unclear",
        target_region="unclear",
        dominance_type="balanced",
        compound_type="hybrid",
        force_vector="mixed",
        kinetic_chain="mixed",
        movement_planes=("multiplanar",),
        body_position="unclear",
        limb_pattern="unclear",
        technical_complexity="moderate",
        primary_muscles=(),
        secondary_muscles=(),
        stabilizers=("transverse_abdominis", "forearm_grip"),
        joint_actions=(("lumbar_spine", ("stabilization",)),),
        stimulus_phase_bias="mixed",
        contraction_phase_emphasis="mixed",
        resistance_profile_type="unclear",
        peak_loading_region="unclear",
        local_fatigue="moderate",
        systemic_fatigue="moderate",
        technical_fatigue="moderate",
        axial_loading="unclear",
        stability_demand="moderate",
        overall_fatigue_cost="moderate",
        sfr_class="context_dependent",
        variations=(
            ("Планка", "контроль корпуса", "снижает внешнюю нагрузку и оставляет задачу удержания положения", "когда движение пока не удается воспроизвести стабильно"),
            ("Тяга сидя в тренажере", "контролируемая траектория", "часть стабилизации берет на себя оборудование", "когда нужно снизить технический риск"),
            ("Румынская тяга с гантелями", "свободная траектория и задняя цепь", "добавляет контроль хвата и положения корпуса", "когда нужна большая свобода настройки"),
            ("Pallof press в кроссовере", "контроль корпуса против вращения", "линия силы задается тросом и легко дозируется", "когда свободный вес неудобен"),
        ),
        alternatives=(
            ("Тренажерная тяга", "позволяет дозировать силовую нагрузку", "траектория фиксированнее и проще контролировать", "когда цель - безопасный тренировочный объем"),
            ("Pallof press", "развивает контроль корпуса", "почти нет движения конечностей, акцент на удержании", "когда нужно снизить сложность"),
            ("Румынская тяга с гантелями", "нагружает заднюю цепь", "имеет понятный тазобедренный паттерн", "когда требуется базовый силовой вариант"),
            ("Тяга верхнего блока", "нагружает мышцы спины", "движение легче стандартизировать", "когда исходное упражнение плохо описано"),
        ),
        supersets=(
            ("суперсет", ("Планка", "Pallof press"), "Сочетает удержание корпуса и контроль вращения без чрезмерной внешней нагрузки.", "Останавливайте подход, если техника становится неузнаваемой."),
            ("трисет", ("Тяга сидя в тренажере", "Румынская тяга с гантелями", "Планка"), "Дает силовую работу для спины, задней цепи и контроля корпуса.", "Не используйте до отказа, пока точная механика упражнения не подтверждена."),
        ),
    )


def rule_for_component(component_id: str) -> ComponentRule | None:
    for rule in RULES:
        if component_id in rule.component_ids:
            return rule
    return None


def choose_rules(decomposition: dict[str, Any]) -> list[ComponentRule]:
    ids = [item.get("component_id") for item in decomposition.get("components") or [] if isinstance(item, dict)]
    rules: list[ComponentRule] = []
    for component_id in ids:
        rule = rule_for_component(component_id or "")
        if rule and rule.family_ru not in {item.family_ru for item in rules}:
            rules.append(rule)
    return rules or [default_rule()]


def source_id(source: dict[str, Any]) -> str | None:
    return source.get("source_id") or source.get("id")


def selected_source_ids(sources: list[dict[str, Any]], limit: int = 5) -> list[str]:
    ranked = sorted(
        [source for source in sources if source_id(source) and not source.get("is_retracted")],
        key=lambda source: {
            "direct": 0,
            "close_variation": 1,
            "same_family": 2,
            "indirect": 3,
            "unclear": 4,
            "not_relevant": 5,
        }.get(str(source.get("exercise_match") or "unclear"), 4),
    )
    return [source_id(source) for source in ranked[:limit] if source_id(source)]


def direct_source_ids(sources: list[dict[str, Any]], limit: int = 5) -> list[str]:
    direct = [
        source_id(source)
        for source in sources
        if source_id(source) and not source.get("is_retracted") and source.get("exercise_match") == "direct"
    ]
    return [item for item in direct[:limit] if item]


def evidence_mode(sources: list[dict[str, Any]]) -> tuple[str, str, int | None, list[str], bool]:
    direct_ids = direct_source_ids(sources)
    if direct_ids:
        return "direct_evidence", "medium", 70, direct_ids, True
    selected = selected_source_ids(sources)
    if selected:
        return "biomechanical_inference", "low", 45, selected, False
    return "expert_inference", "very_low", 25, [], False


def make_claim(
    claim: str,
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    confidence_score: int | None,
) -> dict[str, Any]:
    return {
        "claim": claim,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "source_ids": source_ids,
    }


def muscle_summary(
    muscle_id: str,
    role: str,
    phase_or_range: str,
    rationale: str,
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
) -> dict[str, Any]:
    muscle = MUSCLES[muscle_id]
    return {
        "muscle_id": muscle_id,
        "muscle_name_ru": muscle.name_ru,
        "muscle_group_id": muscle.group_id,
        "role": role,
        "phase_or_range": phase_or_range,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": score,
        "rationale": rationale,
        "source_ids": source_ids,
    }


def joint_action_summary(
    joint_id: str,
    actions: tuple[str, ...],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "joint_id": joint_id,
        "actions": list(actions),
        "primary_phases": ["working_phase", "return_phase"],
        "evidence_type": evidence_type,
        "confidence": confidence,
        "source_ids": source_ids,
    }


def infer_equipment(text: str) -> dict[str, Any]:
    if any(token in text for token in ["cable", "кроссовер", "блок", "трос"]):
        return {
            "modality": "cable",
            "equipment_required": ["cable_station"],
            "external_resistance_type": "cable",
            "line_of_force": "diagonal" if any(token in text for token in ["wood", "chop", "диагон"]) else "mixed",
            "load_placement": "cable_attachment",
        }
    if any(token in text for token in ["dumbbell", "гантел"]):
        equipment = ["dumbbell"]
        if any(token in text for token in ["bench", "скам", "опор", "support"]):
            equipment.append("bench")
        return {
            "modality": "free_weight",
            "equipment_required": unique_strings(equipment),
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": "hands",
        }
    if any(token in text for token in ["barbell", "штанг"]):
        return {
            "modality": "free_weight",
            "equipment_required": ["barbell"],
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": "hands",
        }
    if any(token in text for token in ["machine", "тренажер", "тренажёр"]):
        return {
            "modality": "machine",
            "equipment_required": ["machine"],
            "external_resistance_type": "lever_machine",
            "line_of_force": "machine_guided",
            "load_placement": "machine_pad",
        }
    if any(token in text for token in ["band", "резин"]):
        return {
            "modality": "band",
            "equipment_required": ["resistance_band"],
            "external_resistance_type": "elastic",
            "line_of_force": "elastic_variable",
            "load_placement": "hands",
        }
    if any(token in text for token in ["bodyweight", "собственным весом", "планка", "подтяг", "pull-up"]):
        return {
            "modality": "bodyweight",
            "equipment_required": ["bodyweight_only"],
            "external_resistance_type": "gravity",
            "line_of_force": "vertical_gravity",
            "load_placement": "torso",
        }
    return {
        "modality": "unclear",
        "equipment_required": ["unclear"],
        "external_resistance_type": "unclear",
        "line_of_force": "unclear",
        "load_placement": "unclear",
    }


def combined_text(card: dict[str, Any], ledger: dict[str, Any], decomposition: dict[str, Any]) -> str:
    parts = [
        card.get("exercise_name"),
        card.get("russian_name"),
        " ".join(card.get("aliases") or []),
        ledger.get("notes"),
        decomposition.get("notes"),
    ]
    return normalize_text(" ".join(str(part or "") for part in parts))


def load_or_build_decomposition(card: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    meta = ledger.get("movement_decomposition") if isinstance(ledger.get("movement_decomposition"), dict) else {}
    path_value = meta.get("path") if meta else None
    if path_value:
        path = Path(path_value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return load_decomposition(path)

    entry = {
        "raw_name": ledger.get("russian_name") or card.get("russian_name") or card.get("exercise_name"),
        "russian_name": ledger.get("russian_name") or card.get("russian_name"),
        "exercise_name": ledger.get("exercise_name") or card.get("exercise_name"),
        "exercise_id": ledger.get("exercise_id") or card.get("exercise_id"),
        "aliases": ledger.get("aliases") or card.get("aliases") or [],
        "notes": ledger.get("notes") or "",
    }
    return build_movement_decomposition(entry).to_dict()


def primary_rule(rules: list[ComponentRule]) -> ComponentRule:
    for rule in rules:
        if rule.body_region != "core":
            return rule
    return rules[0]


def merge_rule_values(rules: list[ComponentRule], attr: str) -> list[str]:
    values: list[str] = []
    for rule in rules:
        value = getattr(rule, attr)
        values.extend(value if isinstance(value, tuple) else [value])
    return unique_strings(values)


def fill_classification(card: dict[str, Any], rules: list[ComponentRule], decomposition: dict[str, Any], text: str) -> None:
    main = primary_rule(rules)
    equipment = infer_equipment(text)
    patterns = [pattern for pattern in decomposition.get("taxonomy_patterns") or [] if pattern != "unclear"]
    if not patterns:
        patterns = ["unclear"]

    body_regions = unique_strings([rule.body_region for rule in rules if rule.body_region != "unclear"])
    target_regions = unique_strings([rule.target_region for rule in rules if rule.target_region != "unclear"])
    planes = merge_rule_values(rules, "movement_planes")
    if len([plane for plane in planes if plane != "unclear"]) > 1 and "multiplanar" not in planes:
        planes.append("multiplanar")

    card["exercise_family"] = " + ".join(unique_strings([rule.family_ru for rule in rules]))
    card["category"] = " + ".join(unique_strings([rule.category_ru for rule in rules]))
    card["body_region"] = "full_body" if len(body_regions) > 1 and "core" in body_regions else (body_regions[0] if body_regions else main.body_region)
    card["target_region"] = target_regions[0] if len(target_regions) == 1 else ("full_body" if target_regions else main.target_region)
    card["dominance_type"] = main.dominance_type if len(rules) == 1 else "balanced"
    card["modality"] = equipment["modality"]
    card["equipment_required"] = equipment["equipment_required"]
    card["compound_type"] = "hybrid" if len(rules) > 1 else main.compound_type
    card["movement_patterns"] = patterns
    card["force_vector"] = "mixed" if len({rule.force_vector for rule in rules}) > 1 else main.force_vector
    card["kinetic_chain"] = "mixed" if len({rule.kinetic_chain for rule in rules}) > 1 else main.kinetic_chain
    card["movement_planes"] = unique_strings(planes) or ["unclear"]
    if any(token in text for token in ["support", "опор", "скам", "bench"]):
        card["body_position"] = "supported"
    else:
        card["body_position"] = main.body_position
    card["limb_pattern"] = "unilateral" if any(token in text for token in ["single", "одной ног", "одноопор", "unilateral"]) else main.limb_pattern
    card["technical_complexity"] = "high" if any(rule.technical_complexity == "high" for rule in rules) else main.technical_complexity
    card["contraction_phase_emphasis"] = "mixed" if len({rule.contraction_phase_emphasis for rule in rules}) > 1 else main.contraction_phase_emphasis
    card["stimulus_phase_bias"] = "mixed" if len({rule.stimulus_phase_bias for rule in rules}) > 1 else main.stimulus_phase_bias
    card["display_labels"] = {
        "dominance_label_ru": DISPLAY_DOMINANCE.get(card["dominance_type"], card["dominance_type"]),
        "load_phase_label_ru": DISPLAY_LOAD_PHASE.get(card["stimulus_phase_bias"], card["stimulus_phase_bias"]),
        "contraction_phase_label_ru": DISPLAY_CONTRACTION.get(card["contraction_phase_emphasis"], card["contraction_phase_emphasis"]),
    }


def fill_movement_details(
    card: dict[str, Any],
    decomposition: dict[str, Any],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
    direct: bool,
) -> None:
    details = []
    for component in decomposition.get("components") or []:
        if not isinstance(component, dict):
            continue
        suffix = ""
        if not direct:
            suffix = (
                " Прямые данные по конкретной вариации не найдены; поле заполнено как "
                f"{evidence_type} из компонента {component.get('component_id')} и доступных источников."
            )
        details.append(
            make_claim(
                f"{component.get('label_ru')}: {component.get('description_ru')} {component.get('rationale')}.{suffix}",
                source_ids,
                evidence_type,
                confidence,
                score,
            )
        )
    card["movement_pattern_details"] = details or [
        make_claim(
            "Компонент движения не удалось надежно сопоставить с taxonomy; заполнение ограничено общими аналитическими допущениями.",
            source_ids,
            "expert_inference",
            "very_low",
            25,
        )
    ]


def fill_muscles_and_joints(
    card: dict[str, Any],
    rules: list[ComponentRule],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
) -> None:
    primary = merge_rule_values(rules, "primary_muscles")
    secondary = [item for item in merge_rule_values(rules, "secondary_muscles") if item not in primary]
    stabilizers = [item for item in merge_rule_values(rules, "stabilizers") if item not in primary]
    if not primary and secondary:
        primary, secondary = secondary[:1], secondary[1:]

    card["primary_muscles"] = [
        muscle_summary(
            muscle_id,
            "prime_mover",
            card.get("stimulus_phase_bias") or "mixed",
            "Вывод сделан из распознанных компонентов движения и линии сопротивления; при отсутствии прямых данных это не является EMG-ранжированием.",
            source_ids,
            evidence_type,
            confidence,
            score,
        )
        for muscle_id in primary
        if muscle_id in MUSCLES
    ]
    card["secondary_muscles"] = [
        muscle_summary(
            muscle_id,
            "synergist",
            "mixed",
            "Мышца участвует как синергист по механике сустава и траектории движения.",
            source_ids,
            evidence_type,
            confidence,
            score,
        )
        for muscle_id in secondary
        if muscle_id in MUSCLES
    ]
    card["stabilizers"] = [
        muscle_summary(
            muscle_id,
            "stabilizer",
            "mixed",
            "Мышца удерживает положение корпуса, лопатки, таза или хвата во время выполнения.",
            source_ids,
            evidence_type,
            confidence,
            score,
        )
        for muscle_id in stabilizers
        if muscle_id in MUSCLES
    ]
    joint_map: dict[str, list[str]] = {}
    for rule in rules:
        for joint_id, actions in rule.joint_actions:
            joint_map.setdefault(joint_id, [])
            joint_map[joint_id].extend(actions)
    card["joint_actions"] = [
        joint_action_summary(joint_id, tuple(unique_strings(actions)), source_ids, evidence_type, confidence)
        for joint_id, actions in joint_map.items()
    ]
    card["muscle_stimulus_phase_bias"] = [
        {
            "muscle_id": muscle_id,
            "stimulus_region": card.get("stimulus_phase_bias") or "mixed",
            "rationale": "Фаза стимула оценена по внешнему моменту и положению целевого сустава; это аналитическая оценка, если нет прямых данных по вариации.",
            "evidence_type": evidence_type,
            "confidence": confidence,
            "source_ids": source_ids,
        }
        for muscle_id in primary
        if muscle_id in MUSCLES
    ]
    card["relative_muscle_emphasis"] = [
        {
            "muscle_id": muscle_id,
            "relative_emphasis_score": round(0.82 - index * 0.07, 2),
            "score_type": evidence_type,
            "confidence": confidence,
            "confidence_score": score,
            "rationale": "Относительный акцент выведен из компонентов движения, а не из прямого сравнительного EMG, если прямые данные отсутствуют.",
            "source_ids": source_ids,
        }
        for index, muscle_id in enumerate(primary[:5])
        if muscle_id in MUSCLES
    ]


def phase_text_for_rules(card: dict[str, Any], rules: list[ComponentRule], text: str) -> list[dict[str, str]]:
    title = card.get("russian_name") or card.get("exercise_name") or "упражнение"
    component_ids = {component_id for rule in rules for component_id in rule.component_ids}
    notes_hint = ""
    if "hip_hinge" in component_ids and ("open_hip_rotation" in component_ids or "hip_abduction" in component_ids):
        notes_hint = " Свободная нога продолжает линию корпуса, а таз раскрывается только настолько, насколько сохраняется контроль опорного бедра."
    elif "diagonal_trunk_rotation" in component_ids:
        notes_hint = " Движение идет по диагонали, но таз не должен бесконтрольно проваливаться вслед за тросом."

    if "horizontal_pull" in component_ids:
        return [
            {"phase_id": "start_position", "phase_type": "start_position", "name_ru": "Стартовая позиция", "contraction_type": "isometric", "start": "руки вытянуты к сопротивлению, лопатки под контролем", "end": "корпус стабилен, плечи не уходят к ушам", "events": "настроить корпус, хват и направление локтей"},
            {"phase_id": "working_phase", "phase_type": "concentric", "name_ru": "Тяга к корпусу", "contraction_type": "concentric", "start": "плечи впереди или в нейтрали", "end": "локти прошли назад, лопатки сведены без переразгибания поясницы", "events": "вести локти по выбранной траектории, удерживать ребра вниз"},
            {"phase_id": "peak_phase", "phase_type": "peak_contraction", "name_ru": "Пиковое сведение", "contraction_type": "isometric", "start": "рукоять или снаряд близко к корпусу", "end": "короткая пауза без рывка плечами", "events": "сохранить шею свободной и не заваливать корпус назад"},
            {"phase_id": "return_phase", "phase_type": "return", "name_ru": "Возврат", "contraction_type": "eccentric", "start": "локти согнуты", "end": "руки снова вытянуты с контролем лопаток", "events": "не отпускать вес, сохранять длинную спину"},
        ]
    if "vertical_pull" in component_ids or "shoulder_extension_pull" in component_ids:
        return [
            {"phase_id": "start_position", "phase_type": "start_position", "name_ru": "Стартовая позиция", "contraction_type": "isometric", "start": "плечи подняты к сопротивлению, корпус стабилен", "end": "лопатки готовы к опусканию", "events": "зафиксировать таз и не выводить голову вперед"},
            {"phase_id": "working_phase", "phase_type": "concentric", "name_ru": "Тяга вниз", "contraction_type": "concentric", "start": "руки сверху", "end": "локти или плечи приведены вниз", "events": "вести плечо вниз и к корпусу, не заменять движение отклоном назад"},
            {"phase_id": "peak_phase", "phase_type": "peak_contraction", "name_ru": "Нижняя точка", "contraction_type": "isometric", "start": "широчайшие сокращены", "end": "короткая фиксация без рывка", "events": "удержать лопатки опущенными"},
            {"phase_id": "return_phase", "phase_type": "return", "name_ru": "Контролируемый возврат", "contraction_type": "eccentric", "start": "руки внизу", "end": "плечи снова подняты без потери корпуса", "events": "позволить мышцам растянуться, сохраняя контроль"},
        ]
    if "diagonal_trunk_rotation" in component_ids or "trunk_pelvis_rotation_control" in component_ids:
        return [
            {"phase_id": "start_position", "phase_type": "start_position", "name_ru": "Стартовая диагональ", "contraction_type": "isometric", "start": "корпус развернут к началу траектории", "end": "таз и ребра собраны", "events": "выставить стопы и расстояние до сопротивления"},
            {"phase_id": "working_phase", "phase_type": "concentric", "name_ru": "Ротация или диагональная тяга", "contraction_type": "concentric", "start": "руки и корпус у начала диагонали", "end": "корпус повернут к финальной точке без потери таза", "events": "поворот идет через грудной отдел и таз под контролем"},
            {"phase_id": "peak_phase", "phase_type": "peak_contraction", "name_ru": "Финальный контроль", "contraction_type": "isometric", "start": "сопротивление максимально смещено по диагонали", "end": "короткая фиксация", "events": "не заваливать поясницу и не терять давление в корпусе"},
            {"phase_id": "return_phase", "phase_type": "return", "name_ru": "Возврат по той же дуге", "contraction_type": "eccentric", "start": "финальная диагональ", "end": "исходная диагональ", "events": "возвращаться медленно, не отпускать сопротивление"},
        ]
    if "hip_hinge" in component_ids:
        return [
            {"phase_id": "start_position", "phase_type": "start_position", "name_ru": "Стартовая позиция", "contraction_type": "isometric", "start": f"{title}: корпус наклонен через тазобедренный сустав, нагрузка удерживается под плечом или в руках", "end": "таз, корпус и опорная стопа стабилизированы", "events": "создать опору стопой, сохранить длинную спину и мягкое колено"},
            {"phase_id": "working_phase", "phase_type": "concentric", "name_ru": "Подъем из наклона", "contraction_type": "concentric", "start": "таз согнут, целевые мышцы растянуты", "end": "корпус поднялся до рабочей верхней точки без полной потери наклона", "events": "разгибать бедро, удерживать таз от разворота и не тянуть вес поясницей" + notes_hint},
            {"phase_id": "peak_phase", "phase_type": "peak_contraction", "name_ru": "Верхняя фиксация", "contraction_type": "isometric", "start": "бедро почти разогнуто, таз под контролем", "end": "короткая пауза 1 секунда", "events": "сжать верхне-боковую часть ягодицы опорной ноги и сохранить положение ребер"},
            {"phase_id": "return_phase", "phase_type": "return", "name_ru": "Возврат в нижнюю позицию", "contraction_type": "eccentric", "start": "верхняя рабочая точка", "end": "контролируемый наклон с сохранением длины корпуса", "events": "вести таз назад, не округлять спину и не терять линию свободной ноги"},
        ]
    return [
        {"phase_id": "start_position", "phase_type": "start_position", "name_ru": "Стартовая позиция", "contraction_type": "isometric", "start": "выставлена рабочая стойка и выбранная нагрузка", "end": "корпус и суставы готовы к первому повторению", "events": "проверить амплитуду, хват, опору и отсутствие боли"},
        {"phase_id": "working_phase", "phase_type": "concentric", "name_ru": "Рабочее движение", "contraction_type": "concentric", "start": "начальная точка амплитуды", "end": "целевая рабочая точка", "events": "двигаться по заданной траектории без рывка"},
        {"phase_id": "peak_phase", "phase_type": "peak_contraction", "name_ru": "Контроль конечной точки", "contraction_type": "isometric", "start": "конец рабочей амплитуды", "end": "короткая стабильная пауза", "events": "сохранить положение корпуса и целевых суставов"},
        {"phase_id": "return_phase", "phase_type": "return", "name_ru": "Возврат", "contraction_type": "eccentric", "start": "конечная точка", "end": "исходная позиция", "events": "вернуться медленно и не бросать нагрузку"},
    ]


def fill_biomechanics(
    card: dict[str, Any],
    rules: list[ComponentRule],
    decomposition: dict[str, Any],
    text: str,
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
    direct: bool,
) -> None:
    equipment = infer_equipment(text)
    phases_raw = phase_text_for_rules(card, rules, text)
    phases = [
        {
            "phase_id": item["phase_id"],
            "phase_type": item["phase_type"],
            "name_ru": item["name_ru"],
            "contraction_type": item["contraction_type"],
            "start_position": item["start"],
            "end_position": item["end"],
            "key_events": [item["events"]],
            "evidence_type": evidence_type,
            "confidence": confidence,
            "source_ids": source_ids,
        }
        for item in phases_raw
    ]
    joint_mechanics = []
    for rule in rules:
        for joint_id, actions in rule.joint_actions:
            joint_mechanics.append(
                {
                    "joint_id": joint_id,
                    "phase_id": "working_phase",
                    "primary_actions": list(actions),
                    "rom_characteristic": "large" if joint_id in {"hip", "glenohumeral", "thoracic_spine"} else "moderate",
                    "moment_demand": "high" if joint_id in {"hip", "glenohumeral"} else "moderate",
                    "muscle_function": "Целевые мышцы создают или контролируют момент в суставе согласно распознанному компоненту движения.",
                    "notes": "Если прямых данных по вариации нет, это аналитический перенос из близкого компонента и широкой механики движения.",
                    "evidence_type": evidence_type,
                    "confidence": confidence,
                    "source_ids": source_ids,
                }
            )

    primary_muscles = [item["muscle_id"] for item in card.get("primary_muscles") or []]
    muscle_roles = []
    for muscle_id in primary_muscles[:5]:
        muscle = MUSCLES[muscle_id]
        muscle_roles.append(
            {
                "phase_id": "working_phase",
                "muscle_id": muscle_id,
                "muscle_name_ru": muscle.name_ru,
                "muscle_group_id": muscle.group_id,
                "role": "prime_mover",
                "action": "создает основной внешний момент или удерживает ключевой сегмент движения",
                "joint_action_context": "контекст задан распознанными компонентами движения и линией сопротивления",
                "contraction_type": "concentric",
                "muscle_length_state": "shortening",
                "relative_demand": "high",
                "evidence_type": evidence_type,
                "confidence": confidence,
                "source_ids": source_ids,
            }
        )
        muscle_roles.append(
            {
                "phase_id": "return_phase",
                "muscle_id": muscle_id,
                "muscle_name_ru": muscle.name_ru,
                "muscle_group_id": muscle.group_id,
                "role": "prime_mover",
                "action": "тормозит возврат и удерживает траекторию",
                "joint_action_context": "эксцентрический контроль в обратной части амплитуды",
                "contraction_type": "eccentric",
                "muscle_length_state": "lengthening",
                "relative_demand": "moderate",
                "evidence_type": evidence_type,
                "confidence": confidence,
                "source_ids": source_ids,
            }
        )

    affected_joints = unique_strings([joint_id for rule in rules for joint_id, _ in rule.joint_actions])
    affected_muscles = unique_strings(primary_muscles + [item["muscle_id"] for item in card.get("secondary_muscles") or []])[:8]
    line = equipment["line_of_force"]
    load_placement = equipment["load_placement"]
    vector_effect = {
        "change": "Изменение положения корпуса, таза, лопатки или рукояти меняет расстояние между линией силы и рабочим суставом.",
        "effect_direction": "shifts",
        "affected_joints": affected_joints or ["lumbar_spine"],
        "affected_muscles": affected_muscles or ["transverse_abdominis"],
        "biomechanical_effect": (
            f"Линия силы ({line}) действует через размещение нагрузки ({load_placement}); когда сегмент уходит дальше от линии силы, внешний моментный рычаг растет, "
            "а при приближении к линии силы уменьшается. Поэтому самая трудная часть зависит от угла сустава, положения снаряда и контроля корпуса."
        ),
        "muscle_bias_change": (
            "При увеличении моментного рычага больше акцента получают мышцы, перечисленные как primary_muscles; при снижении рычага часть нагрузки смещается "
            "к стабилизаторам и мышцам, удерживающим траекторию, особенно если техника теряет устойчивость."
        ),
        "evidence_type": evidence_type,
        "confidence": confidence,
        "source_ids": source_ids,
    }

    card["biomechanics"] = {
        "movement_phases": phases,
        "joint_mechanics": joint_mechanics,
        "muscle_roles_by_phase": muscle_roles,
        "external_load_mechanics": {
            "external_resistance_type": equipment["external_resistance_type"],
            "line_of_force": line,
            "load_placement": load_placement,
            "main_moment_arms": [
                {
                    "joint_id": affected_joints[0] if affected_joints else "lumbar_spine",
                    "condition": "моментный рычаг увеличивается, когда снаряд или сегмент тела удаляется от рабочей оси",
                    "effect": "возрастает требование к целевым мышцам и стабилизаторам удерживать положение без компенсации",
                    "affected_muscles": affected_muscles or ["transverse_abdominis"],
                }
            ],
            "vector_shift_effects": [vector_effect],
            "evidence_type": evidence_type,
            "confidence": confidence,
            "source_ids": source_ids,
        },
        "technique_variables": build_technique_variables(card, decomposition, affected_joints, affected_muscles, source_ids, evidence_type, confidence),
        "biomechanical_summary": make_claim(
            biomechanical_summary_text(card, decomposition, direct, evidence_type),
            source_ids,
            evidence_type,
            confidence,
            score,
        ),
    }


def build_technique_variables(
    card: dict[str, Any],
    decomposition: dict[str, Any],
    affected_joints: list[str],
    affected_muscles: list[str],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
) -> list[dict[str, Any]]:
    component_ids = [item.get("component_id") for item in decomposition.get("components") or [] if isinstance(item, dict)]
    variables = [
        {
            "variable_id": "range_of_motion_control",
            "name_ru": "Амплитуда без потери положения",
            "description": "Рабочая амплитуда выбирается до точки, где сохраняется контроль целевых суставов и корпуса.",
            "biomechanical_effect": "Слишком большая амплитуда увеличивает моментный рычаг и часто переносит нагрузку на компенсации вместо целевых мышц.",
        },
        {
            "variable_id": "tempo_and_pause",
            "name_ru": "Темп и пауза",
            "description": "Контролируемый возврат и короткая фиксация в ключевой точке повышают повторяемость траектории.",
            "biomechanical_effect": "Медленный возврат повышает эксцентрический контроль, а пауза снижает инерцию и делает нагрузку более предсказуемой.",
        },
        {
            "variable_id": "load_path",
            "name_ru": "Путь нагрузки относительно тела",
            "description": "Снаряд, рукоять или трос должны идти по траектории, которая соответствует задаче упражнения.",
            "biomechanical_effect": "Смещение нагрузки меняет внешний моментный рычаг и может перенести акцент с целевых мышц на стабилизаторы или соседние суставы.",
        },
    ]
    if "open_hip_rotation" in component_ids:
        variables.append(
            {
                "variable_id": "hip_opening_range",
                "name_ru": "Диапазон раскрытия таза",
                "description": "Таз раскрывается только до угла, где свободная нога продолжает линию корпуса и опорное бедро не проваливается.",
                "biomechanical_effect": "Чрезмерное раскрытие увеличивает ротационный момент вокруг опорного бедра и переносит задачу с ягодичных на компенсации поясницы.",
            }
        )
    return [
        {
            **item,
            "affected_joints": affected_joints or ["lumbar_spine"],
            "affected_muscles": affected_muscles or ["transverse_abdominis"],
            "evidence_type": evidence_type,
            "confidence": confidence,
            "source_ids": source_ids,
        }
        for item in variables
    ]


def biomechanical_summary_text(card: dict[str, Any], decomposition: dict[str, Any], direct: bool, evidence_type: str) -> str:
    component_labels = ", ".join(
        item.get("label_ru", item.get("component_id", "")) for item in decomposition.get("components") or [] if isinstance(item, dict)
    )
    direct_text = "Прямые данные по конкретной вариации найдены и использованы как самый сильный уровень доказательности." if direct else (
        f"Прямые данные по конкретной вариации не найдены; заполнено как {evidence_type} из компонентов: {component_labels}."
    )
    return (
        f"{card.get('russian_name') or card.get('exercise_name')} сочетает компоненты: {component_labels}. "
        f"Основные требования: контролировать линию силы, внешний моментный рычаг и положение суставов, чтобы нагрузка оставалась на заявленных целевых мышцах. {direct_text}"
    )


def fill_load_fatigue_and_sfr(
    card: dict[str, Any],
    rules: list[ComponentRule],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
    direct: bool,
) -> None:
    main = primary_rule(rules)
    equipment = infer_equipment(card_search_text(card))
    caveat = "" if direct else " Прямые данные по конкретной вариации не найдены; значение является аналитической оценкой из компонентов движения."
    card["resistance_profile"] = {
        "profile_type": "variable" if len({rule.resistance_profile_type for rule in rules}) > 1 else main.resistance_profile_type,
        "peak_loading_region": "mixed" if len({rule.peak_loading_region for rule in rules}) > 1 else main.peak_loading_region,
        "explanation": (
            f"Профиль сопротивления определяется типом нагрузки ({equipment['external_resistance_type']}) и тем, как меняется внешний моментный рычаг по амплитуде."
            f"{caveat}"
        ),
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": score,
        "assumptions": [
            "Оценка предполагает контролируемую технику без рывка и без изменения заявленной траектории.",
            "Если оборудование или угол троса отличаются, пик нагрузки может сместиться.",
        ],
        "source_ids": source_ids,
    }
    card["fatigue_cost"] = {
        "local_fatigue": max_fatigue(rules, "local_fatigue"),
        "systemic_fatigue": max_fatigue(rules, "systemic_fatigue"),
        "technical_fatigue": max_fatigue(rules, "technical_fatigue"),
        "axial_loading": max_fatigue(rules, "axial_loading"),
        "stability_demand": max_fatigue(rules, "stability_demand"),
        "overall_fatigue_cost": max_fatigue(rules, "overall_fatigue_cost"),
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": score,
        "assumptions": [
            "Оценка относится к рабочим подходам без отказа и с сохранением техники.",
            "Одноопорные и ротационные компоненты повышают техническую усталость раньше локального отказа.",
        ],
        "source_ids": source_ids,
    }
    card["sfr"] = {
        "sfr_class": "context_dependent" if len({rule.sfr_class for rule in rules}) > 1 else main.sfr_class,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": score,
        "context": (
            "Соотношение стимул/усталость зависит от цели: для локального мышечного объема лучше варианты с меньшей координационной ценой, "
            "для контроля и устойчивости допустима более высокая техническая цена."
        ),
        "assumptions": ["Вес подобран так, чтобы последние повторения не разрушали траекторию."],
        "source_ids": source_ids,
    }


def fatigue_rank(value: str) -> int:
    return {"none": 0, "low": 1, "moderate": 2, "high": 3, "very_high": 4, "unclear": 2}.get(value, 2)


def max_fatigue(rules: list[ComponentRule], attr: str) -> str:
    values = [getattr(rule, attr) for rule in rules]
    return max(values, key=fatigue_rank) if values else "moderate"


def card_search_text(card: dict[str, Any]) -> str:
    return normalize_text(" ".join([card.get("exercise_name") or "", card.get("russian_name") or "", " ".join(card.get("aliases") or [])]))


def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in text_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in text_values(child)]
    return []


def assert_card_text_quality(card: dict[str, Any]) -> None:
    forbidden = [
        "placeholder",
        "todo",
        "не заполнено",
        "шарнир",
        "брейсинг",
        "аксессуар",
        "вЂ",
        "Рќ",
        "СЃ",
    ]
    haystack = "\n".join(text_values(card)).lower()
    for token in forbidden:
        if token.lower() in haystack:
            raise PopulateError(f"Text QA failed: forbidden or placeholder token found: {token}")


def fill_practical_blocks(
    card: dict[str, Any],
    rules: list[ComponentRule],
    decomposition: dict[str, Any],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
) -> None:
    title = card.get("russian_name") or card.get("exercise_name") or "упражнение"
    component_ids = {item.get("component_id") for item in decomposition.get("components") or [] if isinstance(item, dict)}
    if "hip_hinge" in component_ids and "open_hip_rotation" in component_ids:
        card["execution_steps"] = {
            "setup": [
                "Поставьте рядом устойчивую опору для свободной руки: скамью, стойку кроссовера или другой неподвижный предмет.",
                "Встаньте на рабочую ногу, возьмите гантель в противоположную или удобную руку и опустите ее под плечо почти к полу.",
                "Наклоните корпус через тазобедренный сустав почти параллельно полу; свободная нога продолжает линию корпуса назад.",
            ],
            "execution": [
                "Поднимайтесь из наклона не до полной вертикали, а до рабочей верхней точки с сохранением контроля таза.",
                "Одновременно ведите свободную ногу по дуге наружу: колено и носок разворачиваются вверх-наружу, таз раскрывается без рывка.",
                "В верхней точке сожмите верхне-боковую часть ягодицы опорной ноги на 1 секунду.",
            ],
            "rom": [
                "Свободная нога во всех фазах остается продолжением корпуса и не падает ниже линии туловища.",
                "Амплитуда раскрытия таза заканчивается там, где опорная стопа, колено и бедро сохраняют контроль.",
            ],
            "breathing_bracing": [
                "Перед повторением сделайте вдох и создайте давление в корпусе.",
                "Выдыхайте через самый трудный участок подъема, не теряя жесткость корпуса и положение ребер.",
            ],
            "tempo_control": [
                "Возврат в нижнюю позицию выполняйте медленно, примерно 2-3 секунды.",
                "Не используйте инерцию свободной ноги: поворот таза должен быть активным и управляемым.",
            ],
        }
    else:
        card["execution_steps"] = {
            "setup": [
                f"Выставьте исходную позицию для упражнения «{title}» так, чтобы нагрузка двигалась по запланированной траектории.",
                "Подберите вес, при котором можно выполнить все повторения без рывка и потери положения корпуса.",
                "Перед первым повторением проверьте опору, хват и свободную амплитуду движения.",
            ],
            "execution": [
                "Начинайте движение плавно, сохраняя заявленное положение корпуса и рабочих суставов.",
                "Доведите нагрузку до рабочей конечной точки без замены целевого движения компенсацией соседних суставов.",
                "Коротко зафиксируйте ключевую точку, если это не нарушает дыхание и контроль.",
            ],
            "rom": [
                "Работайте в амплитуде, где сохраняются контроль суставов, ровная траектория и отсутствие боли.",
                "Сократите диапазон, если внешняя нагрузка заставляет менять технику.",
            ],
            "breathing_bracing": [
                "Сделайте вдох перед повторением и создайте устойчивое давление в корпусе.",
                "Выдох выполняйте через трудный участок, не расслабляя корпус полностью.",
            ],
            "tempo_control": [
                "Поднимайте или тяните нагрузку без рывка.",
                "Возврат выполняйте контролируемо, обычно медленнее рабочей фазы.",
            ],
        }

    variations = []
    alternatives = []
    supersets = []
    for rule in rules:
        variations.extend(rule.variations)
        alternatives.extend(rule.alternatives)
        supersets.extend(rule.supersets)
    card["variations"] = [
        {
            "name": name,
            "primary_emphasis": emphasis,
            "mechanical_difference": difference,
            "when_to_choose": when,
            "evidence_type": evidence_type,
            "confidence": confidence,
        }
        for name, emphasis, difference, when in unique_tuple_rows(variations)[:4]
    ]
    card["related_variations"] = unique_strings([item["name"] for item in card["variations"]])
    card["alternatives"] = [
        {
            "name": name,
            "similarity": similarity,
            "main_difference": difference,
            "when_to_choose": when,
        }
        for name, similarity, difference, when in unique_tuple_rows(alternatives)[:4]
    ]
    card["supersets_trisets"] = [
        {
            "format": fmt,
            "combination": list(combo),
            "logic": logic,
            "fatigue_warning": warning,
        }
        for fmt, combo, logic, warning in unique_tuple_rows(supersets)[:2]
    ]
    card["common_errors"] = build_common_errors(component_ids, source_ids, evidence_type, confidence)
    card["typical_rep_ranges"] = [
        "6-10 повторений, если приоритет - силовая техника и контроль траектории.",
        "8-15 повторений, если приоритет - мышечный стимул без потери качества движения.",
        "2-4 подхода, оставляя 1-3 повтора в запасе для сложных одноопорных или ротационных вариантов.",
    ]
    card["progression_options"] = [
        "Сначала увеличивайте стабильную амплитуду, затем количество повторений, и только после этого вес.",
        "Усложняйте вариант уменьшением внешней опоры или более медленным возвратом.",
        "Для силового прогресса повышайте нагрузку небольшими шагами при сохранении одинаковой траектории.",
    ]
    card["when_to_avoid_or_modify"] = [
        "Измените упражнение, если появляется боль в рабочем суставе или пояснице.",
        "Снижайте вес или амплитуду, если корпус теряет положение раньше целевых мышц.",
        "Выбирайте более стабильную альтернативу при выраженной усталости, нарушении равновесия или невозможности удержать дыхательное давление.",
    ]
    card["prerequisite_skill_mobility"] = [
        "Умение удерживать корпус без провисания или переразгибания.",
        "Достаточная активная амплитуда рабочих суставов без боли.",
        "Контроль темпа возврата и способность остановить повторение без рывка.",
    ]
    card["mobility_requirements"] = [
        "Рабочая амплитуда целевых суставов без боли.",
        "Контроль таза, ребер и лопаток в выбранной траектории.",
    ]
    card["safety"] = {
        "general": "Начинайте с нагрузки, которая позволяет сохранить одинаковую механику во всех повторениях.",
        "stop_if": ["резкая боль", "онемение", "потеря контроля корпуса или опорного сустава"],
        "load_management": "Увеличивайте нагрузку только после того, как амплитуда и темп остаются стабильными.",
    }
    card["best_use"] = build_best_use(card, rules)


def unique_tuple_rows(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    result = []
    seen = set()
    for row in rows:
        key = row[0]
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def build_common_errors(component_ids: set[str], source_ids: list[str], evidence_type: str, confidence: str) -> list[dict[str, Any]]:
    errors = [
        (
            "Слишком большой вес для выбранной траектории",
            "Инерция сокращает полезный момент в целевых суставах и переносит нагрузку на компенсации.",
            "Уменьшите вес и восстановите одинаковый темп рабочего и обратного участка.",
            "moderate",
        ),
        (
            "Потеря положения корпуса",
            "Меняется линия силы относительно суставов, а стабилизаторы начинают ограничивать движение раньше целевых мышц.",
            "Сократите амплитуду и заново создайте давление в корпусе перед повторением.",
            "moderate",
        ),
        (
            "Смещение нагрузки с целевого сустава",
            "Внешний моментный рычаг уходит в соседний сустав, поэтому мышечный акцент становится другим.",
            "Верните снаряд или рукоять на рабочую линию и контролируйте конечную точку.",
            "moderate",
        ),
    ]
    if "open_hip_rotation" in component_ids:
        errors.insert(
            0,
            (
                "Свободная нога опускается ниже линии корпуса",
                "Таз теряет контролируемое раскрытие, а нагрузка смещается с опорной ягодичной на поясничные компенсации.",
                "Уменьшите амплитуду раскрытия таза и удерживайте свободную ногу продолжением корпуса.",
                "high",
            ),
        )
    return [
        {
            "error": error,
            "biomechanical_consequence": consequence,
            "correction": correction,
            "severity": severity,
            "evidence_type": evidence_type if evidence_type == "direct_evidence" else "expert_inference",
            "confidence": confidence,
            "source_ids": source_ids,
        }
        for error, consequence, correction, severity in errors[:4]
    ]


def build_best_use(card: dict[str, Any], rules: list[ComponentRule]) -> dict[str, str]:
    title = card.get("russian_name") or card.get("exercise_name") or "Это упражнение"
    family = card.get("exercise_family") or rules[0].family_ru
    first_alt = (card.get("alternatives") or [{}])[0]
    summary = (
        f"{title} - это {family}, которое стоит выбирать, когда нужно совместить целевой мышечный стимул с контролем траектории, корпуса и внешней нагрузки. "
        f"Оно может заменить вариант «{first_alt.get('name', 'более простое упражнение')}», если нужна более специфичная механика или другая линия сопротивления. "
        "Ограничение упражнения в том, что техническая цена может стать выше мышечного стимула: если равновесие, хват или положение корпуса ломают повторения, лучше выбрать более стабильную альтернативу."
    )
    return {
        "summary": summary,
        "primary_goal": "мышечный стимул и контроль движения в выбранном паттерне",
        "best_context": "после базового разогрева, когда техника уже стабильна и нагрузку можно дозировать",
        "less_suitable_for": "подходы до отказа, высокая усталость или ситуации, где техника не воспроизводится",
        "hypertrophy": "подходит для умеренных повторений при сохранении контролируемой амплитуды",
        "strength": "подходит как вспомогательное силовое упражнение, если прогресс нагрузки не разрушает механику",
        "skill": "полезно для обучения контроля корпуса, таза, лопаток или линии силы по компонентам движения",
    }


def fill_assumptions_and_evidence(
    card: dict[str, Any],
    decomposition: dict[str, Any],
    sources: list[dict[str, Any]],
    source_ids: list[str],
    evidence_type: str,
    confidence: str,
    score: int | None,
    direct: bool,
) -> None:
    component_ids = [item.get("component_id") for item in decomposition.get("components") or [] if isinstance(item, dict)]
    direct_absent = (
        "Прямые данные по конкретной вариации отсутствуют; поля мышц, фаз, нагрузки и вариантов заполнены как "
        f"{evidence_type} из компонентов {', '.join(component_ids)} и источников {', '.join(source_ids) if source_ids else 'без прямых идентификаторов источников'}."
    )
    card["assumptions"] = unique_strings(
        [
            "Разложение движения выполнено по исходному названию, alias и notes без выбора заранее заданной карточки.",
            "Все нетаксономические компоненты описаны в movement_pattern_details, а enum-поля содержат только значения текущей taxonomy.",
            *(decomposition.get("limitations") or []),
            *(["Для полей без прямых данных использована аналитическая биомеханическая интерпретация компонентов движения."] if not direct else []),
        ]
    )
    card["limitations"] = unique_strings(
        [
            *(decomposition.get("limitations") or []),
            *(["Прямые данные по конкретной вариации найдены и имеют приоритет над данными по семейству упражнения и широкому паттерну."] if direct else [direct_absent]),
            "Идентификаторы источников в карточке указывают на использованные публикации, но не являются автоматическим доказательством каждого поля без отдельного обоснования.",
        ]
    )
    card["not_supported_claims"] = unique_strings(
        [
            "Не утверждать точные проценты активации мышц, если они не извлечены из прямого EMG-источника по этой вариации.",
            "Не утверждать превосходство упражнения над альтернативами без прямого сравнительного исследования.",
            "Не переносить выводы по широкому паттерну движения как прямые данные по конкретной вариации.",
        ]
    )
    card["evidence_summary"] = {
        "source_count": len(sources),
        "direct_match_count": sum(1 for source in sources if source.get("exercise_match") == "direct"),
        "fulltext_count": sum(1 for source in sources if source.get("has_fulltext")),
        "retracted_count": sum(1 for source in sources if source.get("is_retracted")),
        "backends": sorted({backend for source in sources for backend in source.get("source_backends", [])}),
        "providers": sorted({provider for source in sources for provider in source.get("source_providers", [])}),
        "provider_backends": sorted({backend for source in sources for backend in source.get("provider_backends", [])}),
        "population_method": "movement_decomposition_evidence_fill",
        "movement_decomposition_summary": decomposition_summary(decomposition),
    }
    ledger_claims = [
        card["biomechanics"]["biomechanical_summary"],
        *card.get("movement_pattern_details", []),
        make_claim(
            direct_absent if not direct else "Поля карточки заполнялись с приоритетом прямых данных, затем данных по близкой вариации, семейству упражнения и широкому паттерну.",
            source_ids,
            evidence_type,
            confidence,
            score,
        ),
    ]
    card["evidence_ledger"] = ledger_claims


def populate_card_evidence_first(card: dict[str, Any], source_ledger: dict[str, Any]) -> dict[str, Any]:
    populated = copy.deepcopy(card)
    sources = source_ledger.get("sources") or []
    decomposition = load_or_build_decomposition(populated, source_ledger)
    rules = choose_rules(decomposition)
    text = combined_text(populated, source_ledger, decomposition)
    evidence_type, confidence, score, source_ids, direct = evidence_mode(sources)

    fill_classification(populated, rules, decomposition, text)
    fill_movement_details(populated, decomposition, source_ids, evidence_type, confidence, score, direct)
    fill_muscles_and_joints(populated, rules, source_ids, evidence_type, confidence, score)
    fill_biomechanics(populated, rules, decomposition, text, source_ids, evidence_type, confidence, score, direct)
    fill_load_fatigue_and_sfr(populated, rules, source_ids, evidence_type, confidence, score, direct)
    fill_practical_blocks(populated, rules, decomposition, source_ids, evidence_type, confidence)
    fill_assumptions_and_evidence(populated, decomposition, sources, source_ids, evidence_type, confidence, score, direct)

    populated.setdefault("metadata", {})
    populated["metadata"].pop("population_template_id", None)
    populated["metadata"]["populated_at"] = now_iso()
    populated["metadata"]["population_method"] = "movement_decomposition_evidence_fill"
    populated["metadata"]["movement_decomposition"] = decomposition_summary(decomposition)
    populated["metadata"]["schema_version"] = "0.2.0"
    populated["schema_version"] = "0.2.0"
    populated["status"] = "staged_draft"
    assert_card_text_quality(populated)
    return populated


def populate_card(card: dict[str, Any], source_ledger: dict[str, Any]) -> dict[str, Any]:
    return populate_card_evidence_first(card, source_ledger)


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
    parser = argparse.ArgumentParser(description="Populate staged exercise cards from movement decomposition and evidence.")
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
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate = not args.no_validate

    if args.card:
        if not args.sources:
            parser.error("--sources is required with --card.")
        if args.output and args.exercise_id:
            parser.error("--output can only be used with --card.")
        destination = process_one(args.card, args.sources, args.output, validate)
        print(json.dumps({"updated": [str(destination)]}, ensure_ascii=False, indent=2))
        return 0

    if args.exercise_id:
        card_path, sources_path = resolve_paths_from_exercise_id(args.exercise_id)
        destination = process_one(card_path, sources_path, args.output, validate)
        print(json.dumps({"updated": [str(destination)]}, ensure_ascii=False, indent=2))
        return 0

    cards_dir = PROJECT_ROOT / "output" / "exercise_cards"
    updated = []
    for card_path in sorted(cards_dir.glob("*.json")):
        sources_path = PROJECT_ROOT / "output" / "sources" / f"{card_path.stem}.sources.json"
        if not sources_path.exists():
            continue
        updated.append(str(process_one(card_path, sources_path, None, validate)))
    print(json.dumps({"updated": updated}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
