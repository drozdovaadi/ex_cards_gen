# Exercise Card Generation Pipeline

## Purpose

Generate one evidence-backed Russian exercise card for each exercise listed in an input file.

The pipeline is designed for reproducibility: every generated card should be traceable to source records and explicit inference notes.

## Inputs

Supported planned inputs:

- `.txt`: one exercise per line.
- `.md`: one exercise per bullet or line.
- `.csv`: one exercise per row.
- `.xlsx`: one exercise per row.

The first implementation can start with `.txt` and `.md`, then add tabular formats.

## Per-Exercise Workflow

### 1. Normalize Exercise

Create a canonical exercise identity:

- `exercise_id`
- Russian name
- English name when available
- aliases
- exercise family
- variation and variation parent

### 2. Search Evidence

Run independent search branches:

- Amass BioMedCore:
  - biomechanics
  - electromyography / EMG
  - kinematics
  - kinetics
  - muscle activation
  - resistance training
- Life Science Research / NCBI Entrez:
  - PubMed `esearch`
  - PubMed `esummary`
  - PubMed `efetch` when abstracts or metadata are needed
  - PubMed `elink` to find PMCID
- Life Science Research / NCBI PMC:
  - PMC OA check by PMCID

Consensus and Elicit are optional and should be used only when available.

### 3. Normalize Sources

Convert all backend records to one internal source shape:

```json
{
  "source_id": "SRC-001",
  "backend": "amass",
  "title": "",
  "authors": [],
  "journal": "",
  "year": null,
  "pmid": null,
  "doi": null,
  "pmcid": null,
  "abstract": "",
  "study_type": "unclear",
  "evidence_domain": [],
  "exercise_match": "unclear",
  "has_fulltext": false,
  "is_retracted": false,
  "relevance_notes": ""
}
```

### 4. Merge And Rank

Deduplicate by:

- PMID
- DOI
- PMCID
- normalized title

Rank higher:

- direct exercise match
- biomechanics, kinematics, kinetics, EMG, or muscle activation evidence
- systematic reviews and reviews for synthesis
- primary biomechanical studies for movement mechanics
- human studies
- open-access/fulltext availability
- non-retracted sources

### 5. Extract Biomechanics

Populate:

- movement phases
- joint mechanics by phase
- muscle roles by phase
- external load mechanics
- technique variables
- resistance profile
- common errors and consequences

Every claim should be either source-backed or explicitly marked as inference.

### 6. Generate And Validate Card

Write a JSON card using `schemas/exercise_card.schema.json`.

Then validate:

- required fields are present
- taxonomy IDs are valid
- source IDs referenced in the card exist in the source ledger
- unsupported claims are not written as facts

### 7. Save Outputs

For each exercise:

```text
output/exercise_cards/<exercise_id>.json
output/sources/<exercise_id>.sources.json
output/logs/<exercise_id>.log.json
```

## Quality Rules

- Do not merge distinct exercise variations unless the evidence explicitly applies to both.
- Do not convert EMG amplitude directly into hypertrophy claims without caveats.
- Do not treat lack of evidence as evidence of no effect.
- Mark limited evidence clearly.
- Separate direct evidence from biomechanical inference.

