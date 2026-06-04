#!/usr/bin/env python
"""
Collect a mandatory non-Amass literature branch for exercise cards.

The branch uses two keyless open scholarly indexes:
- Europe PMC for biomedical/PubMed-adjacent discovery.
- OpenAlex for broad scholarly discovery and citation metadata.

It follows the same tiered query strategy as the local PubMed branch:
specific variation first, then exercise family, then movement pattern.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from generate_cards import (
    ExerciseEntry,
    PROJECT_ROOT,
    guess_evidence_domains,
    guess_study_type,
    load_exercises,
    normalize_title,
    now_iso,
    parse_year,
    write_json,
)
from research_plan import (
    ResearchPlanError,
    load_research_plan,
    query_specs_for_backend,
    research_plan_summary,
)


OPEN_LITERATURE_PROVIDER = "open_literature"
EUROPE_PMC_BACKEND = "europe_pmc"
OPENALEX_BACKEND = "openalex"
EUROPE_PMC_PROVIDER_BACKEND = "open_literature_europe_pmc"
OPENALEX_PROVIDER_BACKEND = "open_literature_openalex"

class OpenLiteratureError(RuntimeError):
    pass


def merge_backend_query_specs(specs: list[dict[str, Any]], backend: str, by_id: dict[str, dict[str, Any]]) -> None:
    for spec in specs:
        query_id = spec["query_id"]
        existing = by_id.setdefault(
            query_id,
            {
                "query_id": query_id,
                "query_scope": spec["query_scope"],
                "priority": spec["priority"],
                "match_class": spec["match_class"],
                "term_set": spec.get("term_set") or [],
                "movement_component_ids": spec.get("movement_component_ids") or [],
                "research_question_ids": spec.get("research_question_ids") or [],
                "intended_card_fields": spec.get("intended_card_fields") or [],
                "query_kind": spec.get("query_kind") or "llm_dynamic",
                "queries": {},
                "rationale": spec.get("rationale") or "",
            },
        )
        existing["queries"][backend] = spec["query"]


def build_open_literature_query_specs(entry: ExerciseEntry, research_plan: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    merge_backend_query_specs(query_specs_for_backend(research_plan, entry, "europe_pmc"), EUROPE_PMC_BACKEND, by_id)
    merge_backend_query_specs(query_specs_for_backend(research_plan, entry, "openalex"), OPENALEX_BACKEND, by_id)
    specs = sorted(by_id.values(), key=lambda item: (item.get("priority", 99), item.get("query_id") or ""))
    if not specs:
        raise OpenLiteratureError(f"Research plan has no Europe PMC or OpenAlex queries for {entry.exercise_id}.")
    return specs


def source_dedupe_key(source: dict[str, Any]) -> str:
    for field in ("pmid", "doi", "pmcid", "openalex_id"):
        value = source.get(field)
        if value:
            return f"{field}:{str(value).lower()}"
    title = normalize_title(source.get("title") or "")
    if title:
        return f"title:{title}"
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def merge_query_matches(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    matches = []
    seen = set()
    for match in [*(existing.get("query_matches") or []), *(incoming.get("query_matches") or [])]:
        if not isinstance(match, dict):
            continue
        key = (
            match.get("query_id"),
            match.get("query_scope"),
            match.get("priority"),
            match.get("query"),
            match.get("match_source"),
        )
        if key in seen:
            continue
        seen.add(key)
        matches.append(match)
    existing["query_matches"] = sorted(matches, key=lambda item: int(item.get("priority") or 99))


def merge_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        key = source_dedupe_key(source)
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(source)
            continue
        existing["source_backends"] = sorted(
            set(existing.get("source_backends") or []) | set(source.get("source_backends") or [])
        )
        existing["provider_backends"] = sorted(
            set(existing.get("provider_backends") or []) | set(source.get("provider_backends") or [])
        )
        merge_query_matches(existing, source)
        for field, value in source.items():
            if field in {"source_backends", "provider_backends", "query_matches"}:
                continue
            if not existing.get(field) and value:
                existing[field] = value
        existing["has_fulltext"] = bool(existing.get("has_fulltext") or source.get("has_fulltext"))
        existing["is_oa"] = bool(existing.get("is_oa") or source.get("is_oa"))

    return sorted(
        merged.values(),
        key=lambda item: (
            item.get("is_retracted", False),
            min((int(match.get("priority") or 99) for match in item.get("query_matches") or []), default=99),
            item.get("year") is None,
            -(item.get("year") or 0),
            item.get("title") or "",
        ),
    )


def provider_backend_for(backend: str) -> str:
    if backend == EUROPE_PMC_BACKEND:
        return EUROPE_PMC_PROVIDER_BACKEND
    if backend == OPENALEX_BACKEND:
        return OPENALEX_PROVIDER_BACKEND
    return f"open_literature_{backend}"


def query_match(spec: dict[str, Any], backend: str) -> dict[str, Any]:
    return {
        "query_id": spec["query_id"],
        "query_scope": spec["query_scope"],
        "priority": spec["priority"],
        "match_class": spec["match_class"],
        "term_set": spec["term_set"],
        "movement_component_ids": spec.get("movement_component_ids") or [],
        "research_question_ids": spec.get("research_question_ids") or [],
        "intended_card_fields": spec.get("intended_card_fields") or [],
        "query": spec["queries"][backend],
        "match_source": backend,
        "rationale": spec.get("rationale") or "",
    }


def normalize_common_source(
    backend: str,
    spec: dict[str, Any],
    *,
    title: str,
    abstract: str,
    authors: list[str],
    journal: str,
    year: int | None,
    pmid: str | None = None,
    doi: str | None = None,
    pmcid: str | None = None,
    openalex_id: str | None = None,
    url: str | None = None,
    is_oa: bool = False,
    has_fulltext: bool = False,
    is_retracted: bool = False,
    citation_count: int | None = None,
    raw_type: str | None = None,
) -> dict[str, Any]:
    text_for_guess = " ".join([title, abstract, raw_type or ""])
    provider_backend = provider_backend_for(backend)
    return {
        "source_id": None,
        "backend": backend,
        "source_backends": [backend],
        "provider": OPEN_LITERATURE_PROVIDER,
        "provider_backend": provider_backend,
        "source_providers": [OPEN_LITERATURE_PROVIDER],
        "provider_backends": [provider_backend],
        "openalex_id": openalex_id,
        "title": title or "",
        "authors": authors,
        "journal": journal or "",
        "year": year,
        "pmid": pmid,
        "doi": doi,
        "pmcid": pmcid,
        "abstract": abstract or "",
        "url": url,
        "study_type": guess_study_type(text_for_guess),
        "evidence_domain": guess_evidence_domains(text_for_guess),
        "has_fulltext": bool(has_fulltext),
        "is_oa": bool(is_oa),
        "is_retracted": bool(is_retracted),
        "citation_count": citation_count,
        "query_matches": [query_match(spec, backend)],
        "relevance_notes": "Collected from open literature API; relevance requires evidence extraction review.",
    }


def europe_pmc_authors(record: dict[str, Any]) -> list[str]:
    author_list = record.get("authorList") or {}
    authors = author_list.get("author") or []
    result = []
    if isinstance(authors, list):
        for author in authors:
            if isinstance(author, dict) and author.get("fullName"):
                result.append(str(author["fullName"]))
    if result:
        return result
    author_string = record.get("authorString") or ""
    return [part.strip() for part in author_string.split(",") if part.strip()]


def normalize_europe_pmc_records(raw: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    records = raw.get("resultList", {}).get("result", [])
    normalized = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        is_retracted = "retracted" in " ".join(record.get("pubTypeList", {}).get("pubType", [])).lower()
        normalized.append(
            normalize_common_source(
                EUROPE_PMC_BACKEND,
                spec,
                title=record.get("title") or "",
                abstract=record.get("abstractText") or "",
                authors=europe_pmc_authors(record),
                journal=record.get("journalTitle") or record.get("journalInfo", {}).get("journal", {}).get("title") or "",
                year=parse_year(record.get("pubYear") or record.get("firstPublicationDate")),
                pmid=record.get("pmid"),
                doi=record.get("doi"),
                pmcid=record.get("pmcid"),
                url=record.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url")
                if isinstance(record.get("fullTextUrlList", {}).get("fullTextUrl"), list)
                and record.get("fullTextUrlList", {}).get("fullTextUrl")
                else None,
                is_oa=str(record.get("isOpenAccess") or "").upper() == "Y",
                has_fulltext=bool(record.get("pmcid") or record.get("hasFullText") == "Y"),
                is_retracted=is_retracted,
                citation_count=parse_int(record.get("citedByCount")),
                raw_type=" ".join(record.get("pubTypeList", {}).get("pubType", [])),
            )
        )
    return normalized


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def reconstruct_openalex_abstract(index: dict[str, Any] | None) -> str:
    if not isinstance(index, dict) or not index:
        return ""
    positions: dict[int, str] = {}
    for word, raw_positions in index.items():
        if not isinstance(raw_positions, list):
            continue
        for position in raw_positions:
            if isinstance(position, int):
                positions[position] = word
    if not positions:
        return ""
    return " ".join(positions[index] for index in sorted(positions))


def openalex_authors(record: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in record.get("authorships") or []:
        if isinstance(authorship, dict):
            author = authorship.get("author") or {}
            name = author.get("display_name")
            if name:
                authors.append(str(name))
    return authors


def normalize_openalex_records(raw: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    records = raw.get("results", [])
    normalized = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        primary_location = record.get("primary_location") or {}
        source = primary_location.get("source") or {}
        normalized.append(
            normalize_common_source(
                OPENALEX_BACKEND,
                spec,
                title=record.get("display_name") or "",
                abstract=reconstruct_openalex_abstract(record.get("abstract_inverted_index")),
                authors=openalex_authors(record),
                journal=source.get("display_name") or "",
                year=parse_year(record.get("publication_year")),
                doi=normalize_openalex_doi(record.get("doi")),
                openalex_id=record.get("id"),
                url=record.get("doi") or record.get("id"),
                is_oa=bool((record.get("open_access") or {}).get("is_oa")),
                has_fulltext=bool(record.get("has_fulltext") or (record.get("open_access") or {}).get("oa_url")),
                is_retracted=bool(record.get("is_retracted")),
                citation_count=parse_int(record.get("cited_by_count")),
                raw_type=record.get("type"),
            )
        )
    return normalized


def normalize_openalex_doi(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text.removeprefix("https://doi.org/").removeprefix("http://doi.org/")


def http_get_json(url: str, params: dict[str, Any], timeout_sec: int, retries: int, pause_sec: float) -> tuple[dict[str, Any], str]:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            full_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "exercise-card-generator/0.1 (local open literature branch)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if pause_sec > 0:
                time.sleep(pause_sec)
            return payload, full_url
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                raise
        time.sleep(min(8.0, 1.0 + attempt * 2.0))
    raise OpenLiteratureError(f"HTTP request failed: {last_error}")


def search_europe_pmc(spec: dict[str, Any], retmax: int, timeout_sec: int, retries: int, pause_sec: float) -> tuple[dict[str, Any], str]:
    return http_get_json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        {
            "query": spec["queries"][EUROPE_PMC_BACKEND],
            "format": "json",
            "pageSize": retmax,
        },
        timeout_sec=timeout_sec,
        retries=retries,
        pause_sec=pause_sec,
    )


def search_openalex(spec: dict[str, Any], retmax: int, timeout_sec: int, retries: int, pause_sec: float) -> tuple[dict[str, Any], str]:
    return http_get_json(
        "https://api.openalex.org/works",
        {
            "search": spec["queries"][OPENALEX_BACKEND],
            "per-page": retmax,
            "sort": "relevance_score:desc",
        },
        timeout_sec=timeout_sec,
        retries=retries,
        pause_sec=pause_sec,
    )


def write_raw(raw_dir: Path, entry: ExerciseEntry, spec: dict[str, Any], backend: str, url: str, payload: Any) -> str:
    raw_path = raw_dir / entry.exercise_id / f"{spec['query_id']}.{backend}.json"
    raw_record = {
        "fetched_at": now_iso(),
        "provider": OPEN_LITERATURE_PROVIDER,
        "backend": backend,
        "url": url,
        "query_spec": spec,
        "response": payload,
    }
    write_json(raw_path, raw_record)
    return str(raw_path)


def process_exercise(entry: ExerciseEntry, args: argparse.Namespace) -> dict[str, Any]:
    research_plan = args.research_plan_data
    query_specs = build_open_literature_query_specs(entry, research_plan)
    research_info = research_plan_summary(research_plan, entry)
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else PROJECT_ROOT / args.raw_dir
    results: list[dict[str, Any]] = []
    backend_logs: list[dict[str, Any]] = []
    raw_files: list[str] = []

    for spec in query_specs:
        for backend, search_fn, normalizer in [
            (EUROPE_PMC_BACKEND, search_europe_pmc, normalize_europe_pmc_records),
            (OPENALEX_BACKEND, search_openalex, normalize_openalex_records),
        ]:
            if backend not in spec.get("queries", {}):
                continue
            try:
                raw, url = search_fn(spec, args.retmax, args.timeout_sec, args.retries, args.pause_sec)
                raw_files.append(write_raw(raw_dir, entry, spec, backend, url, raw))
                normalized = normalizer(raw, spec)
                results.extend(normalized)
                backend_logs.append(
                    {
                        "backend": backend,
                        "provider": OPEN_LITERATURE_PROVIDER,
                        "provider_backend": provider_backend_for(backend),
                        "status": "ok",
                        "query_id": spec["query_id"],
                        "query_scope": spec["query_scope"],
                        "query": spec["queries"][backend],
                        "source_count": len(normalized),
                        "url": url,
                    }
                )
            except Exception as exc:
                backend_logs.append(
                    {
                        "backend": backend,
                        "provider": OPEN_LITERATURE_PROVIDER,
                        "provider_backend": provider_backend_for(backend),
                        "status": "error",
                        "query_id": spec["query_id"],
                        "query_scope": spec["query_scope"],
                        "query": spec["queries"][backend],
                        "error": str(exc),
                    }
                )
                if args.fail_fast:
                    raise

    merged = merge_sources(results)
    return {
        "exercise_id": entry.exercise_id,
        "exercise_name": entry.exercise_name,
        "russian_name": entry.russian_name,
        "aliases": entry.aliases,
        "query_strategy": "llm_dynamic_research_plan",
        "research_plan": research_info,
        "query_specs": query_specs,
        "queries_used": [
            {"backend": backend, "query": spec["queries"][backend]}
            for spec in query_specs
            for backend in [EUROPE_PMC_BACKEND, OPENALEX_BACKEND]
            if backend in spec["queries"]
        ],
        "backend_logs": backend_logs,
        "raw_files": raw_files,
        "results": merged,
    }


def build_results_document(input_file: Path, exercises: list[ExerciseEntry], args: argparse.Namespace) -> dict[str, Any]:
    output: dict[str, Any] = {
        "generated_at": now_iso(),
        "input_file": str(input_file),
        "provider": OPEN_LITERATURE_PROVIDER,
        "provider_backends": [EUROPE_PMC_PROVIDER_BACKEND, OPENALEX_PROVIDER_BACKEND],
        "backends": [EUROPE_PMC_BACKEND, OPENALEX_BACKEND],
        "query_strategy": "llm_dynamic_research_plan",
        "exercise_count": len(exercises),
        "exercises": [],
    }
    for index, entry in enumerate(exercises, start=1):
        if not args.quiet:
            print(f"[{index}/{len(exercises)}] open_literature: {entry.exercise_id}", file=sys.stderr)
        exercise_payload = process_exercise(entry, args)
        output["exercises"].append(exercise_payload)
        output[entry.exercise_id] = exercise_payload
    return output


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Europe PMC + OpenAlex literature results.")
    parser.add_argument("input_file", type=Path, help="Path to .txt, .md, or .csv input file.")
    parser.add_argument("--retmax", type=int, default=10, help="Maximum results per query per backend.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "open_literature_results.json",
        help="Where to write the normalized open-literature result JSON.",
    )
    parser.add_argument(
        "--research-plan",
        type=Path,
        required=True,
        help="LLM-authored research plan JSON. Search queries are not generated from local templates.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "output" / "logs" / "open_literature_raw",
        help="Directory for exact raw API responses.",
    )
    parser.add_argument("--timeout-sec", type=int, default=30, help="HTTP timeout per request.")
    parser.add_argument("--retries", type=int, default=2, help="Retry count for transient HTTP failures.")
    parser.add_argument("--pause-sec", type=float, default=0.1, help="Polite pause after each successful request.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop on the first provider error.")
    parser.add_argument("--quiet", action="store_true", help="Do not print per-exercise progress to stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args(argv)
    input_file = args.input_file if args.input_file.is_absolute() else PROJECT_ROOT / args.input_file
    if not input_file.exists():
        raise SystemExit(f"Input file not found: {input_file}")
    exercises = load_exercises(input_file)
    if not exercises:
        raise SystemExit(f"No exercises found in input file: {input_file}")

    research_plan_path = args.research_plan if args.research_plan.is_absolute() else PROJECT_ROOT / args.research_plan
    try:
        args.research_plan_data = load_research_plan(research_plan_path)
    except ResearchPlanError as exc:
        raise SystemExit(str(exc)) from exc

    output_path = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    result = build_results_document(input_file, exercises, args)
    write_json(output_path, result)
    summary = {
        "output": str(output_path),
        "exercise_count": len(exercises),
        "source_count": sum(len(item.get("results") or []) for item in result["exercises"]),
        "backend_error_count": sum(
            1
            for item in result["exercises"]
            for log in item.get("backend_logs") or []
            if log.get("status") == "error"
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
