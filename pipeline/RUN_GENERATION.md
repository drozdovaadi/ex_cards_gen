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

Before any backend search, Codex/LLM must create a per-exercise research plan:

- The plan is written to `output/logs/<run_id>.research_plan.json`.
- Search strings are selected by exercise-specific analysis, not by local query templates.
- The plan contains research questions, rationale, backend query strings, `query_scope`, `priority`, `match_class`, and intended card fields.
- `specific_variation`, `exercise_family`, and `movement_pattern` are provenance/ranking labels only.

Family and movement-pattern results are supplemental; they should fill gaps or support general mechanics, not override direct evidence for the exact variation.

## Steps

### 1. Write LLM Research Plan

Create `output/logs/<run_id>.research_plan.json` manually from LLM analysis of each exercise. Do not use fixed search-query templates.

Minimum query item shape:

```json
{
  "query_id": "specific_variation_bar_path",
  "query_scope": "specific_variation",
  "priority": 1,
  "match_class": "direct",
  "research_question_ids": ["bar_path_and_touch_point"],
  "intended_card_fields": [
    "biomechanics.external_load_mechanics.vector_shift_effects",
    "biomechanics.technique_variables"
  ],
  "queries": {
    "pubmed": "\"bench press\" \"bar path\" biomechanics",
    "europe_pmc": "\"bench press\" AND \"bar path\" AND biomechanics",
    "openalex": "bench press bar path biomechanics",
    "amass": "\"bench press\" \"bar path\" biomechanics"
  },
  "rationale": "The query targets a concrete exercise-specific technique variable."
}
```

### 2. Run Open Literature Search

```powershell
python pipeline\open_literature.py input\exercises.txt --retmax 10 --output output\logs\open_literature_results.json --research-plan output\logs\<run_id>.research_plan.json
```

Outputs:

```text
output/logs/open_literature_results.json
output/logs/open_literature_raw/<exercise_id>/<query_id>.<backend>.json
```

This branch executes the Europe PMC and OpenAlex search strings from the LLM research plan.

### 3. Optional: Build Amass Query Plan

```powershell
python pipeline\amass_queries.py input\exercises.txt --research-plan output\logs\<run_id>.research_plan.json
```

Outputs:

```text
output/logs/amass_query_plan.json
output/logs/amass_results.scaffold.json
```

### 4. Optional: Run Amass MCP Searches

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

The staging script deduplicates records per exercise by `pmid`, `doi`, `amassId`, `pmcid`, and normalized title. It also attaches `query_matches` to every result with `query_id`, `query_scope`, `priority`, `query`, `research_question_ids`, `intended_card_fields`, and `rationale`.

If only a legacy aggregate Amass file exists, restage it with:

```powershell
python pipeline\stage_amass_results.py --plan output\logs\amass_query_plan.json --input output\logs\amass_results.json --output output\logs\amass_results.json
```

Legacy records without query provenance are marked with inferred query matches only when their text matches terms explicitly present in the LLM research plan.

Expected shape:

```json
{
  "barbell_squat": {
    "exercise_id": "barbell_squat",
    "exercise_name": "barbell squat",
    "russian_name": "barbell squat",
    "aliases": [],
    "query_strategy": "llm_dynamic_research_plan",
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

### 5. Run Source Staging And NCBI Merge

```powershell
python pipeline\generate_cards.py input\exercises.txt --retmax 10 --literature-json output\logs\open_literature_results.json --research-plan output\logs\<run_id>.research_plan.json
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

`output/exercise_cards/` is the default card destination. Use a different
card output directory only when the user explicitly requests it.

### 6. Prepare Evidence-First Biomechanics

```powershell
python pipeline\populate_card.py --all
```

This command must not apply hardcoded movement templates. It prepares cards for
per-field source extraction and removes any legacy template-populated
biomechanical fields when run on previously populated cards. The old
controlled-template command path has been removed; production cards must use the
evidence-first/no-template route only.

The next analysis step must fill each field from:

1. direct exact-variation evidence;
2. close-variation evidence, explicitly marked as indirect;
3. same-family evidence, explicitly marked as analytical;
4. broad movement-pattern evidence, only with a caveat.

This updates cards in:

```text
output/exercise_cards/
```

### 7. Verify

At minimum:

```powershell
python -c "import ast, pathlib; [ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['pipeline/research_plan.py','pipeline/open_literature.py','pipeline/amass_raw.py','pipeline/amass_queries.py','pipeline/stage_amass_results.py','pipeline/generate_cards.py','pipeline/populate_card.py','pipeline/run_generation.py']]; print('OK')"
```

For a real run, also inspect:

```text
output/logs/generation_report.json
output/sources/<exercise_id>.sources.json
output/exercise_cards/<exercise_id>.json
```

## Failure Rules

- Do not run `open_literature.py`, `amass_queries.py`, `generate_cards.py`, or `run_generation.py` without an LLM-authored `--research-plan`.
- Do not run `generate_cards.py` without at least one secondary branch: `output/logs/open_literature_results.json` or `output/logs/amass_results.json`.
- Do not treat NCBI-only output as complete.
- Do not stage final Amass results from chat memory; save raw MCP responses through `pipeline/amass_raw.py save`.
- If open_literature and Amass both return no results for an exercise, record the gap and have the LLM revise the research plan with better aliases or broader evidence questions before generating a final card.
- If direct variation evidence is sparse, use `exercise_family` and `movement_pattern` evidence as explicitly marked supplemental support.
- Do not fill phases, muscle roles, load peaks, vector shifts, variations, alternatives, or programming fields from local movement templates.
- If a field lacks direct evidence, fill it only by a documented analytical inference from suitable studies; otherwise keep it unresolved and record the limitation.
