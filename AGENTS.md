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
2. Run Amass and NCBI/PubMed searches as independent mandatory search branches.
3. Normalize source records to the project source format.
4. Merge and deduplicate Amass and NCBI sources by PMID, DOI, PMCID, and normalized title.
5. Rank evidence by directness, study type, relevance, source quality, and full-text availability.
6. Fetch additional metadata or PMCID/open-access availability when useful.
7. Generate a schema-valid `staged_draft` card and source ledger.
8. Populate structured biomechanics with `pipeline/populate_card.py`.
9. Keep template-derived claims marked as `biomechanical_inference` or `expert_inference`.
10. Validate against `schemas/exercise_card.schema.json`.
11. Save the card, source JSON, and generation log.

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
