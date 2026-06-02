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
  - Amass BioMedCore for enriched biomedical literature records.
  - Life Science Research / NCBI Entrez for PubMed search, summaries, fetches, and PubMed-to-PMC linking.
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
2. Build a tiered Amass query plan with `pipeline/amass_queries.py`.
3. Run Amass MCP searches and save raw per-query JSON under `output/logs/amass_raw/<exercise_id>/<query_id>.json`.
4. Stage Amass raw results with `pipeline/stage_amass_results.py` so every record has `query_matches`.
5. Run tiered NCBI/PubMed source staging with `pipeline/generate_cards.py`.
6. Normalize source records to the project source format.
7. Merge and deduplicate Amass and NCBI sources by PMID, DOI, PMCID, and normalized title.
8. Rank evidence by directness, study type, relevance, source quality, and full-text availability.
9. Fetch additional metadata or PMCID/open-access availability when useful.
10. Generate a schema-valid `staged_draft` card and source ledger.
11. Populate structured biomechanics with `pipeline/populate_card.py`.
12. Keep template-derived claims marked as `biomechanical_inference` or `expert_inference`.
13. Validate against `schemas/exercise_card.schema.json`.
14. Save the card, source JSON, and generation log.

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
