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
13. Populate structured biomechanics with `pipeline/populate_card.py`.
14. Keep template-derived claims marked as `biomechanical_inference` or `expert_inference`.
15. Validate against `schemas/exercise_card.schema.json`.
16. Save the card, source JSON, and generation log.

## Card Architecture

Exercise cards have two layers:

- Summary layer: classification, target muscles, recommendations, errors, safety, fatigue, and practical usage.
- Biomechanics layer: phases, muscle roles by phase, joint mechanics, external load mechanics, technique variables, and an evidence-backed biomechanical summary.

Muscles, joints, movement patterns, phases, load mechanics, and evidence fields should use stable taxonomy IDs from `schemas/taxonomies/`.

## Output Layout

```text
output/
  exercise_cards/
    <exercise_id>.json
  sources/
    <exercise_id>.sources.json
  logs/
    <exercise_id>.log.json
```
