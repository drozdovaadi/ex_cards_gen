# Exercise Card Generator Project Rules

## Scope

This project builds a reproducible pipeline for generating Russian exercise cards from an input exercise list.

The expected user command is:

```text
сгенерируй карточки для упражнений из списка в файле <filename>
```

The expected output is one structured exercise card per exercise, plus source/audit files in `output/`.

## Context Rules

- Treat this project as a clean project. Do not rely on context from other chats or unrelated projects.
- Do not use the `ai-fitness-vibecode-orchestrator` skill in this project.
- Prefer project-local documentation, schemas, and taxonomies over assumptions from prior work.
- If a future instruction conflicts with this file, ask for clarification before changing the project contract.

## Evidence Rules

- Use scientific sources before web sources.
- Search each exercise with a tiered strategy:
  - `specific_variation`, priority 1: exact exercise variation and technique terms.
  - `exercise_family`, priority 2: same exercise family, used as supplemental evidence.
  - `movement_pattern`, priority 3: broad movement pattern, used only as indirect support.
- Do not let `exercise_family` or `movement_pattern` results outrank direct `specific_variation` evidence.
- Mandatory search backends for each exercise:
  - Life Science Research / NCBI Entrez for PubMed search, summaries, fetches, and PubMed-to-PMC linking.
  - At least one independent secondary literature branch:
    - `open_literature` through Europe PMC + OpenAlex when Amass is unavailable.
    - Amass BioMedCore when account limits allow it.
  - Life Science Research / NCBI PMC for open-access availability by PMCID.
- Optional backends:
  - Consensus, only when account/search limits allow it.
  - Elicit, only when API access is available.
- Do not invent DOI, PMID, PMCID, authors, journal names, or findings.
- Mark indirect inference as `biomechanical_inference`, `expert_inference`, or `evidence_informed_estimate`.
- If the evidence is weak or missing, record that explicitly in `limitations` and `not_supported_claims`.
- Do not populate exercise characteristics from local movement templates. Direct exercise evidence has priority; if a field lacks direct evidence, fill it only by a documented analytical inference from suitable close-variation, same-family, or movement-pattern studies.
- Do not treat source IDs as proof for a field unless the fact was extracted from the source or the analytical inference is explicitly documented.

## Pipeline Rules

Process exercises one at a time.

For each exercise:

1. Normalize the exercise name and known aliases.
2. Run `pipeline/open_literature.py` to collect Europe PMC + OpenAlex results unless a complete Amass batch is available.
3. Optionally build a tiered Amass query plan with `pipeline/amass_queries.py`.
4. Optionally run Amass MCP searches and save each exact raw response with `pipeline/amass_raw.py save` under `output/logs/amass_raw/<exercise_id>/<query_id>.json`.
5. Optionally audit and stage Amass raw results with `pipeline/stage_amass_results.py` so every record has `query_matches`.
6. Run tiered NCBI/PubMed source staging with `pipeline/generate_cards.py`, passing `--literature-json` and optional `--amass-json`.
8. Normalize source records to the project source format.
9. Merge and deduplicate open_literature, optional Amass, and NCBI sources by PMID, DOI, PMCID, and normalized title.
10. Rank evidence by directness, study type, relevance, source quality, and full-text availability.
11. Fetch additional metadata or PMCID/open-access availability when useful.
12. Generate a schema-valid `staged_draft` card and source ledger.
13. Prepare structured biomechanics with `pipeline/populate_card.py`; the default route must not apply local movement templates.
14. Fill missing biomechanical fields through direct extraction or documented analytical inference from suitable studies; do not use template-derived claims for production cards.
15. Validate against `schemas/exercise_card.schema.json`.
16. Save the card, source JSON, and generation log.

## Card Architecture

Exercise cards have two layers:

- Summary layer: classification, target muscles, recommendations, errors, safety, fatigue, and practical usage.
- Biomechanics layer: phases, muscle roles by phase, joint mechanics, external load mechanics, technique variables, and an evidence-backed biomechanical summary.

Muscles, joints, movement patterns, phases, load mechanics, and evidence fields should use stable taxonomy IDs from `schemas/taxonomies/`.

## Card Quality Rules

- Describe exercise phases, load peaks, load-vector shifts, and downstream biomechanical consequences in detail. Do not leave generic phase labels without start/end positions, key events, joint demands, and compensation risks.
- Keep user-facing Russian text grammatical, semantically clear, and natural. Avoid mixed-language coaching jargon in Russian prose. For example, write `напряжение корпуса` or `внутрибрюшное давление` instead of `брейсинг`, and `вспомогательное упражнение` instead of `аксессуарное упражнение`.
- Do not use the word `шарнир` in user-facing Russian text. For hip-hinge mechanics, write natural phrases such as `наклон через тазобедренный сустав`, `сгибание и разгибание в тазобедренном суставе`, or `наклон таза назад`.
- Do not phrase source synthesis as the claim itself. Write the biomechanical fact in the field, not `Систематический обзор ... поддерживает ...`. Example: write `Высокий вклад задней поверхности бедра`, while source support belongs in source/evidence fields.
- Keep machine taxonomy IDs stable, but add human-readable Russian labels through `display_labels`:
  - `dominance_label_ru`, for example `Сбалансированное`.
  - `load_phase_label_ru`, for example `Растянутая`.
  - `contraction_phase_label_ru`, for example `Смешанная`.
- `execution_steps` is a required visible card block named `Пошаговая техника выполнения`; it must contain setup, execution, range-of-motion, breathing/body-pressure, and tempo-control steps.
- `alternatives`, `variations`, and `supersets_trisets` must contain concrete exercise examples, not placeholders. Variations and alternatives should explain what changes mechanically, when to choose each option, and what tradeoff it creates.
- `supersets_trisets` is a required visible card block named `Суперсеты и трисеты`; it must explicitly state the advantage of each concrete combination and the fatigue/technique warning for using it.
- `best_use.summary` is required and must be rendered as the final card block named `Когда выбирать это упражнение`. It should be a coherent summary paragraph: what the exercise is, when to choose it, what it is an alternative to, and what limitation/tradeoff makes another option preferable.
- `biomechanics.external_load_mechanics.vector_shift_effects[*].biomechanical_effect` must explain how the line of force and external moment arm change, and `muscle_bias_change` must explicitly state which muscles receive more or less emphasis.
- Use the current 10-card set in `output/exercise_cards/` as the reference level of detail and structure for technique, biomechanics, alternatives, supersets/trisets, and final best-use summaries.

## Output Layout

Unless the user explicitly requests another destination, save all generated
exercise cards to:

```text
C:\new_ex_gen\output\exercise_cards
```

```text
output/
  exercise_cards/
    <exercise_id>.json
  sources/
    <exercise_id>.sources.json
  logs/
    <exercise_id>.log.json
```
