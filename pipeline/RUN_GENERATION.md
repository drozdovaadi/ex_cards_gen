# Full Generation Run Protocol

This protocol is the project-level sequence for the command:

```text
сгенерируй карточки для упражнений из списка в файле <filename>
```

## Contract

Both source branches are mandatory:

- Amass BioMedCore through Codex MCP.
- Life Science Research / NCBI through local `generate_cards.py`.

The local Python pipeline does not call Amass directly. The Codex agent is responsible for the Amass MCP calls and for saving their results into `output/logs/amass_results.json`.

Both branches must use the same tiered search order:

1. `specific_variation`, priority 1: exact exercise variation and technique.
2. `exercise_family`, priority 2: broader exercise family.
3. `movement_pattern`, priority 3: similar movement pattern, indirect support only.

Family and movement-pattern results are supplemental; they should fill gaps or support general mechanics, not override direct evidence for the exact variation.

## Steps

### 1. Build Amass Query Plan

```powershell
python pipeline\amass_queries.py input\exercises.txt
```

Outputs:

```text
output/logs/amass_query_plan.json
output/logs/amass_results.scaffold.json
```

### 2. Run Amass MCP Searches

For each item in `amass_query_plan.json`:

1. Run every query in `exercises[].queries` in ascending `priority` order.
2. Use tool `mcp__codex_apps__amass._search_amass_biomedcore_records`.
3. Save each raw MCP response as:

```text
output/logs/amass_raw/<exercise_id>/<query_id>.json
```

4. Stage the raw responses into the final Amass result file:

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

### 3. Run Source Staging And NCBI Merge

```powershell
python pipeline\generate_cards.py input\exercises.txt --retmax 10 --amass-json output\logs\amass_results.json
```

Outputs:

```text
output/exercise_cards/<exercise_id>.json
output/sources/<exercise_id>.sources.json
output/logs/<exercise_id>.log.json
```

### 4. Populate Biomechanics

```powershell
python pipeline\populate_card.py --all
```

This updates cards in:

```text
output/exercise_cards/
```

### 5. Verify

At minimum:

```powershell
python -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['pipeline/amass_queries.py','pipeline/stage_amass_results.py','pipeline/generate_cards.py','pipeline/populate_card.py']]; print('OK')"
```

For a real run, also inspect:

```text
output/logs/generation_report.json
output/sources/<exercise_id>.sources.json
output/exercise_cards/<exercise_id>.json
```

## Failure Rules

- Do not run `generate_cards.py` without `output/logs/amass_results.json`.
- Do not treat NCBI-only output as complete.
- If Amass returns no results for an exercise, record the gap and rerun with broader aliases before generating a final card.
- If direct variation evidence is sparse, use `exercise_family` and `movement_pattern` evidence as explicitly marked supplemental support.
- If no movement template matches in `populate_card.py`, leave the card as a staged draft and record the limitation.
