#!/usr/bin/env python
"""
Utilities for LLM-authored per-exercise research plans.

The project intentionally does not generate literature search strings from
fixed local templates. A Codex/LLM step must analyze each exercise first and
write a research plan. Local Python scripts only validate, normalize, execute,
and preserve provenance for the searches described in that plan.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


QUERY_SCOPE_PRIORITIES = {
    "specific_variation": 1,
    "exercise_family": 2,
    "movement_pattern": 3,
}

QUERY_SCOPE_MATCH_CLASS = {
    "specific_variation": "direct",
    "exercise_family": "same_family",
    "movement_pattern": "indirect",
}

BACKEND_ALIASES = {
    "pubmed": ["pubmed", "ncbi_pubmed", "ncbi", "life_science_research"],
    "europe_pmc": ["europe_pmc", "europepmc"],
    "openalex": ["openalex", "open_alex"],
    "amass": ["amass", "amass_biomedcore"],
}


class ResearchPlanError(RuntimeError):
    pass


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def load_research_plan(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ResearchPlanError(f"Research plan not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ResearchPlanError(f"Invalid research plan JSON: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ResearchPlanError("Research plan must be a JSON object.")
    if not isinstance(data.get("exercises"), list):
        raise ResearchPlanError("Research plan must contain an exercises[] list.")
    return data


def exercise_plan_for_entry(plan: dict[str, Any], entry: Any) -> dict[str, Any]:
    exercise_id = getattr(entry, "exercise_id", "")
    names = {
        normalize_key(exercise_id),
        normalize_key(getattr(entry, "exercise_name", "")),
        normalize_key(getattr(entry, "russian_name", "")),
        normalize_key(getattr(entry, "raw_name", "")),
    }
    names.update(normalize_key(alias) for alias in getattr(entry, "aliases", []) or [])
    names.discard("")

    for exercise in plan.get("exercises", []):
        if not isinstance(exercise, dict):
            continue
        candidates = {
            normalize_key(exercise.get("exercise_id")),
            normalize_key(exercise.get("exercise_name")),
            normalize_key(exercise.get("russian_name")),
            normalize_key(exercise.get("raw_name")),
        }
        candidates.update(normalize_key(alias) for alias in exercise.get("aliases") or [])
        candidates.discard("")
        if names & candidates:
            return exercise

    raise ResearchPlanError(
        f"Research plan does not contain an exercise entry matching {exercise_id!r}."
    )


def backend_query_from_item(query: dict[str, Any], backend: str) -> str:
    backend_key = normalize_key(backend)
    aliases = BACKEND_ALIASES.get(backend_key, [backend_key])
    query_maps = [
        query.get("queries"),
        query.get("backend_queries"),
        query.get("search_queries"),
    ]
    for query_map in query_maps:
        if not isinstance(query_map, dict):
            continue
        normalized_map = {normalize_key(key): value for key, value in query_map.items()}
        for alias in aliases:
            value = normalized_map.get(normalize_key(alias))
            if isinstance(value, str) and normalize_space(value):
                return normalize_space(value)

    common_query = query.get("query")
    if isinstance(common_query, str) and normalize_space(common_query):
        return normalize_space(common_query)
    return ""


def normalize_query_item(query: dict[str, Any], backend: str) -> dict[str, Any] | None:
    query_text = backend_query_from_item(query, backend)
    if not query_text:
        return None

    scope = query.get("query_scope") or query.get("scope") or "specific_variation"
    scope = str(scope)
    priority = query.get("priority", QUERY_SCOPE_PRIORITIES.get(scope, 99))
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        priority = QUERY_SCOPE_PRIORITIES.get(scope, 99)

    match_class = query.get("match_class") or QUERY_SCOPE_MATCH_CLASS.get(scope, "unclear")
    query_id = query.get("query_id") or query.get("id") or f"{scope}_{normalize_key(backend)}_{priority}"

    return {
        "query_id": normalize_key(query_id),
        "query_scope": scope,
        "priority": priority,
        "match_class": match_class,
        "term_set": query.get("term_set") or query.get("key_terms") or [],
        "movement_component_ids": query.get("movement_component_ids") or [],
        "research_question_ids": query.get("research_question_ids") or [],
        "intended_card_fields": query.get("intended_card_fields") or [],
        "query_kind": query.get("query_kind") or "llm_dynamic",
        "query": query_text,
        "rationale": query.get("rationale") or query.get("why_this_query") or "",
    }


def query_specs_for_backend(plan: dict[str, Any], entry: Any, backend: str) -> list[dict[str, Any]]:
    exercise = exercise_plan_for_entry(plan, entry)
    queries = exercise.get("queries") or exercise.get("search_queries") or []
    if not isinstance(queries, list):
        raise ResearchPlanError(
            f"Research plan queries for {getattr(entry, 'exercise_id', '')!r} must be a list."
        )

    specs = []
    seen: set[tuple[str, str]] = set()
    for query in queries:
        if not isinstance(query, dict):
            continue
        spec = normalize_query_item(query, backend)
        if spec is None:
            continue
        key = (spec["query_id"], spec["query"])
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)

    specs.sort(key=lambda item: (item.get("priority", 99), item.get("query_id") or ""))
    return specs


def require_query_specs(plan: dict[str, Any], entry: Any, backend: str) -> list[dict[str, Any]]:
    specs = query_specs_for_backend(plan, entry, backend)
    if not specs:
        raise ResearchPlanError(
            f"Research plan has no {backend} queries for {getattr(entry, 'exercise_id', '')!r}."
        )
    return specs


def research_plan_summary(plan: dict[str, Any], entry: Any) -> dict[str, Any]:
    exercise = exercise_plan_for_entry(plan, entry)
    research_questions = exercise.get("research_questions") or []
    queries = exercise.get("queries") or exercise.get("search_queries") or []
    return {
        "strategy": plan.get("strategy") or "llm_dynamic_research_plan",
        "exercise_id": exercise.get("exercise_id") or getattr(entry, "exercise_id", ""),
        "reasoning_summary": exercise.get("reasoning_summary") or "",
        "research_question_count": len(research_questions) if isinstance(research_questions, list) else 0,
        "query_count": len(queries) if isinstance(queries, list) else 0,
    }
