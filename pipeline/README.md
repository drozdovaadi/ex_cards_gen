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

Current CLI:

```powershell
python pipeline\amass_queries.py input\exercises.txt
python pipeline\amass_raw.py next --limit 1
python pipeline\amass_raw.py save --exercise-id <exercise_id> --query-id <query_id>
python pipeline\amass_raw.py audit --require-complete
python pipeline\stage_amass_results.py --plan output\logs\amass_query_plan.json --raw-dir output\logs\amass_raw --output output\logs\amass_results.json
python pipeline\open_literature.py input\exercises.txt --retmax 10 --output output\logs\open_literature_results.json
python pipeline\generate_cards.py input\exercises.txt --retmax 10 --literature-json output\logs\open_literature_results.json
python pipeline\populate_card.py --all
```

When Amass is available, add `--amass-json output\logs\amass_results.json` to the `generate_cards.py` command.

The mandatory source contract is Life Science Research / NCBI PubMed plus at least one independent secondary literature branch. Use `pipeline/open_literature.py` for the default branch through Europe PMC + OpenAlex. Amass JSON is optional enrichment when account limits allow it. See `pipeline/RUN_GENERATION.md`.

Input line format:

```text
Румынская тяга | Romanian deadlift | RDL
barbell squat
```

When a Russian exercise name is used, add an English alias after `|` for better PubMed search quality.

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

Run independent mandatory search branches:

- Tiered exercise query strategy:
  - `specific_variation` first: exact technique and variation terms are authoritative when present.
  - `exercise_family` second: same family evidence fills gaps and supports broader mechanics.
  - `movement_pattern` third: similar pattern evidence is indirect and cannot override variation-specific findings.
- open_literature:
  - Europe PMC
  - OpenAlex
  - biomechanics
  - electromyography / EMG
  - kinematics
  - kinetics
  - muscle activation
  - resistance training
- Optional Amass BioMedCore:
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

The current local CLI implements the Life Science Research / NCBI PubMed branch and accepts `--literature-json` from `pipeline/open_literature.py`. Amass itself is available to the Codex chat agent as an MCP backend, not as a local Python API, so saved Amass MCP result JSON is passed through optional `--amass-json`.

open_literature, optional Amass, and NCBI use the same tiered search profile so their results can be merged and ranked consistently.
Raw Amass MCP responses must be saved per query under `output/logs/amass_raw/<exercise_id>/<query_id>.json`, then staged with `pipeline/stage_amass_results.py`. The staging step attaches `query_matches` to each source and deduplicates records before `generate_cards.py` runs.

Useful Amass raw commands:

```powershell
python pipeline\amass_raw.py manifest --exercise-id barbell_front_squat
python pipeline\amass_raw.py next --exercise-id barbell_front_squat --limit 2
python pipeline\amass_raw.py save --exercise-id barbell_front_squat --query-id specific_variation_biomechanics_core
python pipeline\amass_raw.py audit --exercise-id barbell_front_squat
```

`save` reads the raw Amass MCP JSON response from stdin by default. It stores the exact response, records SHA-256/byte count/record count in `output/logs/amass_raw_manifest.json`, and keeps the raw file parseable by `stage_amass_results.py`.

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
  "query_matches": [],
  "has_fulltext": false,
  "is_retracted": false,
  "relevance_notes": ""
}
```

### 4. Merge And Rank

open_literature, optional Amass, and NCBI/PubMed results are merged into one source ledger. Amass is no longer treated as a blocker when account limits prevent use.

Deduplicate by:

- PMID
- DOI
- PMCID
- normalized title

Rank higher:

- direct `specific_variation` exercise match
- same-family evidence only after direct evidence
- broad movement-pattern evidence only as indirect support
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

### 6.1 Populate Biomechanics

After source staging, populate structured biomechanical fields:

```powershell
python pipeline\populate_card.py --exercise-id romanian_deadlift
python pipeline\populate_card.py --all
```

The current population step uses controlled movement templates and source IDs from the merged open_literature + NCBI ledger, with optional Amass sources when available. Template-supported movement families include:

- squat
- split squat / lunge
- Romanian deadlift / hinge
- deadlift
- bench press
- hip thrust / glute bridge

If no template matches, the card remains a staged draft and records the limitation explicitly.

### 7. Save Outputs

For each exercise:

```text
output/exercise_cards/<exercise_id>.json
output/sources/<exercise_id>.sources.json
output/logs/<exercise_id>.log.json
```

Amass staging also writes:

```text
output/logs/amass_results.json
```

## Quality Rules

- Do not merge distinct exercise variations unless the evidence explicitly applies to both.
- Do not convert EMG amplitude directly into hypertrophy claims without caveats.
- Do not treat lack of evidence as evidence of no effect.
- Mark limited evidence clearly.
- Separate direct evidence from biomechanical inference.
