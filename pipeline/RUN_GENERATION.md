# Full Generation Run Protocol

This protocol is the project-level sequence for the command:

```text
сгенерируй карточки для упражнений из списка в файле <filename>
```

## Contract

The mandatory source contract is:

- Life Science Research / NCBI through local `generate_cards.py`.
- At least one independent secondary literature branch:
  - default: `open_literature` through Europe PMC + OpenAlex;
  - optional enrichment: Amass BioMedCore through Codex MCP when account limits allow it.

The local Python pipeline does not call Amass directly. If Amass is used, the Codex agent is responsible for the Amass MCP calls and for saving every raw per-query response into `output/logs/amass_raw/<exercise_id>/<query_id>.json` with `pipeline/amass_raw.py save`.

Both branches must use the same tiered search order:

1. `specific_variation`, priority 1: exact exercise variation and technique.
2. `exercise_family`, priority 2: broader exercise family.
3. `movement_pattern`, priority 3: similar movement pattern, indirect support only.

Family and movement-pattern results are supplemental; they should fill gaps or support general mechanics, not override direct evidence for the exact variation.

## Steps

### 1. Run Open Literature Search

```powershell
python pipeline\open_literature.py input\exercises.txt --retmax 10 --output output\logs\open_literature_results.json
```

Outputs:

```text
output/logs/open_literature_results.json
output/logs/open_literature_raw/<exercise_id>/<query_id>.<backend>.json
```

This branch uses Europe PMC and OpenAlex with the same `specific_variation` -> `exercise_family` -> `movement_pattern` priority order.

### 2. Optional: Build Amass Query Plan

```powershell
python pipeline\amass_queries.py input\exercises.txt
```

Outputs:

```text
output/logs/amass_query_plan.json
output/logs/amass_results.scaffold.json
```

### 3. Optional: Run Amass MCP Searches

Use the raw helper to get the next missing query:

```powershell
python pipeline\amass_raw.py next --limit 1
```

For each missing item:

1. Run every query in `exercises[].queries` in ascending `priority` order.
2. Use tool `mcp__codex_apps__amass._search_amass_biomedcore_records`.
3. Pipe or paste the exact JSON response into:

```powershell
python pipeline\amass_raw.py save --exercise-id <exercise_id> --query-id <query_id>
```

This writes:

```text
output/logs/amass_raw/<exercise_id>/<query_id>.json
output/logs/amass_raw_manifest.json
```

Audit coverage before staging:

```powershell
python pipeline\amass_raw.py audit --require-complete
```

For partial batches, scope audit to the current exercise:

```powershell
python pipeline\amass_raw.py audit --exercise-id <exercise_id>
```

Stage the raw responses into the final Amass result file:

```powershell
python pipeline\stage_amass_results.py --plan output\logs\amass_query_plan.json --raw-dir output\logs\amass_raw --output output\logs\amass_results.json
```

The staging script deduplicates records per exercise by `pmid`, `doi`, `amassId`, `pmcid`, and normalized title. It also attaches `query_matches` to every result with `query_id`, `query_scope`, `priority`, and `query`.

If only a legacy aggregate Amass file exists, restage it with:

```powershell
python pipeline\stage_amass_results.py --plan output\logs\amass_query_plan.json --input output\logs\amass_results.json --output output\logs\amass_results.json
```

Legacy records without query provenance are marked with inferred query matches when the title/abstract contains terms from the tiered query plan.

Expected shape:

```json
{
  "barbell_squat": {
    "exercise_id": "barbell_squat",
    "exercise_name": "barbell squat",
    "russian_name": "barbell squat",
    "aliases": [],
    "query_strategy": "tiered_specific_then_family_then_pattern",
    "query_specs": [],
    "queries_used": ["..."],
    "results": []
  }
}
```

Each `results` item should preserve Amass fields such as:

- `amassId`
- `pmid`
- `doi`
- `title`
- `abstract`
- `authors`
- `journal`
- `publicationDate`
- `citationCount`
- `journalQualityJufo`
- `hasFulltext`
- `isRetracted`
- `query_matches`

### 4. Run Source Staging And NCBI Merge

```powershell
python pipeline\generate_cards.py input\exercises.txt --retmax 10 --literature-json output\logs\open_literature_results.json
```

When Amass is available, add:

```powershell
--amass-json output\logs\amass_results.json
```

Outputs:

```text
output/exercise_cards/<exercise_id>.json
output/sources/<exercise_id>.sources.json
output/logs/<exercise_id>.log.json
```

### 5. Populate Biomechanics

```powershell
python pipeline\populate_card.py --all
```

This updates cards in:

```text
output/exercise_cards/
```

### 6. Verify

At minimum:

```powershell
python -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['pipeline/open_literature.py','pipeline/amass_raw.py','pipeline/amass_queries.py','pipeline/stage_amass_results.py','pipeline/generate_cards.py','pipeline/populate_card.py']]; print('OK')"
```

For a real run, also inspect:

```text
output/logs/generation_report.json
output/sources/<exercise_id>.sources.json
output/exercise_cards/<exercise_id>.json
```

## Failure Rules

- Do not run `generate_cards.py` without at least one secondary branch: `output/logs/open_literature_results.json` or `output/logs/amass_results.json`.
- Do not treat NCBI-only output as complete.
- Do not stage final Amass results from chat memory; save raw MCP responses through `pipeline/amass_raw.py save`.
- If open_literature and Amass both return no results for an exercise, record the gap and rerun with broader aliases before generating a final card.
- If direct variation evidence is sparse, use `exercise_family` and `movement_pattern` evidence as explicitly marked supplemental support.
- If no movement template matches in `populate_card.py`, leave the card as a staged draft and record the limitation.
