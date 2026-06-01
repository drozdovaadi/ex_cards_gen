#!/usr/bin/env python
"""
Generate staged exercise-card drafts from an input exercise list.

This first implementation focuses on the reproducible infrastructure:
- read exercise names from input files;
- run the Life Science Research / NCBI Entrez branch locally;
- require saved Amass MCP output as the second mandatory source branch;
- normalize and deduplicate PubMed sources;
- write source ledgers and schema-valid staged draft cards.

Amass is intentionally not called from this script because the Amass MCP is
available to the Codex chat agent, not as a local Python API in this project.
The project pipeline requires the agent to save Amass results and pass them to
this script with --amass-json so Amass and NCBI results are always merged.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "exercise_card.schema.json"


CYRILLIC_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


@dataclass(frozen=True)
class ExerciseEntry:
    raw_name: str
    russian_name: str
    exercise_name: str
    exercise_id: str
    aliases: list[str]


class PipelineError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def has_cyrillic(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def looks_english(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value)) and not has_cyrillic(value)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str) -> str:
    lowered = value.strip().lower().translate(CYRILLIC_TRANSLIT)
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"exercise_{digest}"


def strip_markdown_list_marker(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^[-*+]\s+", "", line)
    line = re.sub(r"^\d+[.)]\s+", "", line)
    return line.strip()


def parse_exercise_tokens(raw_value: str) -> ExerciseEntry | None:
    value = normalize_space(strip_markdown_list_marker(raw_value))
    if not value or value.startswith("#"):
        return None

    if "|" in value:
        tokens = [normalize_space(token) for token in value.split("|") if normalize_space(token)]
    else:
        tokens = [value]

    if not tokens:
        return None

    raw_name = tokens[0]
    english_alias = next((token for token in tokens if looks_english(token)), None)
    russian_name = raw_name
    exercise_name = english_alias or raw_name
    aliases = []
    for token in tokens:
        if token != raw_name and token not in aliases:
            aliases.append(token)

    return ExerciseEntry(
        raw_name=raw_name,
        russian_name=russian_name,
        exercise_name=exercise_name,
        exercise_id=slugify(english_alias or raw_name),
        aliases=aliases,
    )


def load_exercises(input_path: Path) -> list[ExerciseEntry]:
    suffix = input_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        entries: list[ExerciseEntry] = []
        for line in input_path.read_text(encoding="utf-8-sig").splitlines():
            entry = parse_exercise_tokens(line)
            if entry:
                entries.append(entry)
        return entries

    if suffix == ".csv":
        return load_exercises_from_csv(input_path)

    raise PipelineError(f"Unsupported input format: {input_path.suffix}. Use .txt, .md, or .csv.")


def load_exercises_from_csv(input_path: Path) -> list[ExerciseEntry]:
    entries: list[ExerciseEntry] = []
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(2048)
        handle.seek(0)
        has_header = csv.Sniffer().has_header(sample) if sample.strip() else False
        if has_header:
            reader = csv.DictReader(handle)
            for row in reader:
                name = (
                    row.get("exercise")
                    or row.get("exercise_name")
                    or row.get("name")
                    or row.get("russian_name")
                    or ""
                )
                aliases = row.get("aliases") or row.get("alias") or row.get("english_name") or ""
                raw = " | ".join(part for part in [name, aliases] if part)
                entry = parse_exercise_tokens(raw)
                if entry:
                    entries.append(entry)
        else:
            reader = csv.reader(handle)
            for row in reader:
                raw = " | ".join(cell for cell in row if cell.strip())
                entry = parse_exercise_tokens(raw)
                if entry:
                    entries.append(entry)
    return entries


def find_ncbi_entrez_script() -> Path:
    home = Path.home()
    candidates = sorted(
        home.glob(
            ".codex/plugins/cache/openai-curated/life-science-research/*/"
            "skills/ncbi-entrez-skill/scripts/ncbi_entrez.py"
        )
    )
    if not candidates:
        raise PipelineError(
            "Could not find Life Science Research ncbi_entrez.py script under "
            f"{home / '.codex/plugins/cache/openai-curated/life-science-research'}"
        )
    return candidates[-1]


class NcbiEntrezClient:
    def __init__(self, log_dir: Path, timeout_sec: int = 45) -> None:
        self.script_path = find_ncbi_entrez_script()
        self.log_dir = log_dir
        self.timeout_sec = timeout_sec
        self.raw_files: list[str] = []

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = subprocess.run(
            [sys.executable, str(self.script_path)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=self.timeout_sec,
            check=False,
        )
        if process.returncode != 0:
            raise PipelineError(
                "NCBI Entrez script failed with exit code "
                f"{process.returncode}: {process.stderr.strip()}"
            )
        try:
            result = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"NCBI Entrez returned non-JSON output: {process.stdout}") from exc
        if not result.get("ok", False):
            raise PipelineError(f"NCBI Entrez error: {result.get('error', result)}")
        raw_output_path = result.get("raw_output_path")
        if raw_output_path:
            self.raw_files.append(str(raw_output_path))
        return result

    def esearch_pubmed(self, query: str, retmax: int) -> list[str]:
        result = self.run(
            {
                "endpoint": "esearch",
                "params": {
                    "db": "pubmed",
                    "term": query,
                    "retmode": "json",
                    "retmax": retmax,
                },
                "max_items": retmax,
            }
        )
        return [str(item) for item in result.get("records", [])]

    def efetch_pubmed_xml(self, pmids: list[str], label: str) -> Path:
        raw_output_path = self.log_dir / f"{label}_pubmed_efetch.xml"
        self.run(
            {
                "endpoint": "efetch",
                "params": {
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "xml",
                },
                "response_format": "xml",
                "max_items": len(pmids),
                "save_raw": True,
                "raw_output_path": str(raw_output_path),
            }
        )
        return raw_output_path

    def elink_pubmed_to_pmc(self, pmid: str, label: str) -> str | None:
        raw_output_path = self.log_dir / f"{label}_pmid_{pmid}_elink_pmc.json"
        self.run(
            {
                "endpoint": "elink",
                "params": {
                    "dbfrom": "pubmed",
                    "db": "pmc",
                    "id": pmid,
                    "retmode": "json",
                },
                "max_items": 10,
                "save_raw": True,
                "raw_output_path": str(raw_output_path),
            }
        )
        try:
            raw = json.loads(raw_output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for linkset in raw.get("linksets", []):
            for linkset_db in linkset.get("linksetdbs", []) or []:
                if linkset_db.get("dbto") != "pmc":
                    continue
                links = linkset_db.get("links") or []
                if links:
                    return f"PMC{links[0]}"
        return None


def build_pubmed_queries(entry: ExerciseEntry) -> list[str]:
    search_terms = [entry.exercise_name, *entry.aliases]
    search_terms = [term for term in search_terms if term and looks_english(term)]
    if not search_terms:
        search_terms = [entry.exercise_name]

    quoted_terms = " OR ".join(f'"{term}"' for term in dict.fromkeys(search_terms))
    if len(search_terms) > 1:
        exercise_part = f"({quoted_terms})"
    else:
        exercise_part = quoted_terms

    return [
        (
            f"{exercise_part} AND "
            '(biomechanics OR electromyography OR EMG OR kinematics OR kinetics '
            'OR "muscle activation" OR "resistance training")'
        )
    ]


def parse_pubmed_xml(xml_path: Path) -> list[dict[str, Any]]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    records = []
    for article in root.findall(".//PubmedArticle"):
        records.append(parse_pubmed_article(article))
    return records


def parse_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if not value:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return int(match.group(0)) if match else None


def node_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return normalize_space("".join(node.itertext()))


def parse_pubmed_article(article: ET.Element) -> dict[str, Any]:
    pmid = node_text(article.find("./MedlineCitation/PMID"))
    article_node = article.find("./MedlineCitation/Article")
    title = node_text(article_node.find("./ArticleTitle") if article_node is not None else None)
    journal = node_text(article_node.find("./Journal/Title") if article_node is not None else None)
    if not journal:
        journal = node_text(article_node.find("./Journal/ISOAbbreviation") if article_node is not None else None)

    abstract_parts = []
    if article_node is not None:
        for abstract_text in article_node.findall("./Abstract/AbstractText"):
            label = abstract_text.attrib.get("Label")
            text = node_text(abstract_text)
            if label and text:
                abstract_parts.append(f"{label}: {text}")
            elif text:
                abstract_parts.append(text)
    abstract = "\n".join(abstract_parts)

    authors = []
    if article_node is not None:
        for author in article_node.findall("./AuthorList/Author"):
            collective = node_text(author.find("./CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            last = node_text(author.find("./LastName"))
            fore = node_text(author.find("./ForeName"))
            full = normalize_space(f"{fore} {last}")
            if full:
                authors.append(full)

    article_ids = article.findall("./PubmedData/ArticleIdList/ArticleId")
    doi = None
    pmcid = None
    for article_id in article_ids:
        id_type = article_id.attrib.get("IdType")
        value = node_text(article_id)
        if id_type == "doi":
            doi = value
        elif id_type == "pmc":
            pmcid = value

    publication_types = [
        node_text(node)
        for node in article.findall("./MedlineCitation/Article/PublicationTypeList/PublicationType")
        if node_text(node)
    ]

    year = extract_publication_year(article)
    text_for_guess = " ".join([title, abstract, " ".join(publication_types)])
    return {
        "pmid": pmid or None,
        "doi": doi,
        "pmcid": pmcid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "year": year,
        "publication_types": publication_types,
        "study_type": guess_study_type(text_for_guess),
        "evidence_domain": guess_evidence_domains(text_for_guess),
        "is_retracted": any("Retracted Publication" == item for item in publication_types),
    }


def extract_publication_year(article: ET.Element) -> int | None:
    candidate_paths = [
        "./MedlineCitation/Article/ArticleDate/Year",
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        "./MedlineCitation/DateCompleted/Year",
        "./MedlineCitation/DateRevised/Year",
    ]
    for path in candidate_paths:
        text = node_text(article.find(path))
        if text.isdigit():
            return int(text)

    medline_date = node_text(article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate"))
    match = re.search(r"\b(19|20)\d{2}\b", medline_date)
    return int(match.group(0)) if match else None


def guess_study_type(text: str) -> str:
    lowered = text.lower()
    if "meta-analysis" in lowered or "meta analysis" in lowered:
        return "meta_analysis"
    if "systematic review" in lowered:
        return "systematic_review"
    if "review" in lowered:
        return "review"
    if "randomized" in lowered or "randomised" in lowered:
        return "randomized_trial"
    if "electromyography" in lowered or " emg " in f" {lowered} ":
        return "emg_study"
    if "kinematic" in lowered:
        return "kinematic_study"
    if "kinetic" in lowered:
        return "kinetic_study"
    if "biomechan" in lowered:
        return "biomechanics_lab"
    if "model" in lowered or "simulation" in lowered:
        return "musculoskeletal_modeling"
    return "unclear"


def guess_evidence_domains(text: str) -> list[str]:
    lowered = text.lower()
    domains = []
    checks = [
        ("biomechanics", ["biomechan"]),
        ("kinematics", ["kinematic"]),
        ("kinetics", ["kinetic", "joint moment", "ground reaction"]),
        ("emg", ["electromyography", " emg ", "myoelectric"]),
        ("muscle_activation", ["muscle activation"]),
        ("strength", ["strength", "1rm", "one-repetition maximum"]),
        ("fatigue", ["fatigue"]),
        ("injury_risk", ["injury", "risk"]),
        ("technique", ["technique", "posture", "stance", "grip"]),
        ("equipment", ["machine", "smith", "barbell", "dumbbell", "cable"]),
    ]
    padded = f" {lowered} "
    for domain, needles in checks:
        if any(needle in padded for needle in needles):
            domains.append(domain)
    return domains or ["unclear"]


def classify_exercise_match(source: dict[str, Any], entry: ExerciseEntry) -> str:
    haystack = normalize_title(" ".join([source.get("title") or "", source.get("abstract") or ""]))
    terms = [entry.exercise_name, *entry.aliases, entry.raw_name]
    normalized_terms = [normalize_title(term) for term in terms if term]
    if any(term and term in haystack for term in normalized_terms):
        return "direct"
    return "unclear"


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def run_ncbi_source_branch(entry: ExerciseEntry, log_dir: Path, retmax: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = NcbiEntrezClient(log_dir=log_dir)
    queries = build_pubmed_queries(entry)
    pmids: list[str] = []
    for query in queries:
        for pmid in client.esearch_pubmed(query, retmax=retmax):
            if pmid not in pmids:
                pmids.append(pmid)

    branch_log: dict[str, Any] = {
        "backend": "ncbi_pubmed",
        "status": "ok",
        "queries_used": queries,
        "pmids": pmids,
        "raw_files": client.raw_files,
    }

    if not pmids:
        return [], branch_log

    xml_path = client.efetch_pubmed_xml(pmids, label=entry.exercise_id)
    records = parse_pubmed_xml(xml_path)

    for record in records:
        if not record.get("pmcid") and record.get("pmid"):
            record["pmcid"] = client.elink_pubmed_to_pmc(record["pmid"], label=entry.exercise_id)

    branch_log["raw_files"] = client.raw_files
    return [normalize_ncbi_source(record, entry) for record in records], branch_log


def normalize_ncbi_source(record: dict[str, Any], entry: ExerciseEntry) -> dict[str, Any]:
    pmcid = record.get("pmcid")
    return {
        "source_id": None,
        "backend": "ncbi_pubmed",
        "source_backends": ["ncbi_pubmed"],
        "title": record.get("title") or "",
        "authors": record.get("authors") or [],
        "journal": record.get("journal") or "",
        "year": record.get("year"),
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "pmcid": pmcid,
        "abstract": record.get("abstract") or "",
        "study_type": record.get("study_type") or "unclear",
        "evidence_domain": record.get("evidence_domain") or ["unclear"],
        "exercise_match": classify_exercise_match(record, entry),
        "has_fulltext": bool(pmcid),
        "is_retracted": bool(record.get("is_retracted")),
        "relevance_notes": "Collected by PubMed query; relevance requires evidence extraction review.",
    }


def load_amass_sources(amass_paths: list[Path], entry: ExerciseEntry) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    for raw_path in amass_paths:
        path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
        if not path.exists():
            logs.append({"backend": "amass", "status": "error", "path": str(path), "error": "file not found"})
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            payload = data.get(entry.exercise_id, data) if isinstance(data, dict) else data
            results = payload.get("results", payload) if isinstance(payload, dict) else payload
            if not isinstance(results, list):
                raise ValueError("expected a list or an object with a 'results' list")
            normalized = [normalize_amass_source(result, entry) for result in results if isinstance(result, dict)]
            sources.extend(normalized)
            logs.append(
                {
                    "backend": "amass",
                    "status": "ok",
                    "path": str(path),
                    "source_count": len(normalized),
                }
            )
        except Exception as exc:
            logs.append({"backend": "amass", "status": "error", "path": str(path), "error": str(exc)})
    return sources, logs


def normalize_amass_source(record: dict[str, Any], entry: ExerciseEntry) -> dict[str, Any]:
    text_for_guess = " ".join([record.get("title") or "", record.get("abstract") or ""])
    source = {
        "source_id": None,
        "backend": "amass",
        "source_backends": ["amass"],
        "amass_id": record.get("amassId"),
        "title": record.get("title") or "",
        "authors": record.get("authors") or [],
        "journal": record.get("journal") or "",
        "year": parse_year(record.get("publicationDate")),
        "pmid": record.get("pmid"),
        "doi": record.get("doi"),
        "pmcid": record.get("pmcid"),
        "abstract": record.get("abstract") or "",
        "study_type": guess_study_type(text_for_guess),
        "evidence_domain": guess_evidence_domains(text_for_guess),
        "exercise_match": "unclear",
        "has_fulltext": bool(record.get("hasFulltext") or record.get("pmcid")),
        "is_retracted": bool(record.get("isRetracted")),
        "citation_count": record.get("citationCount"),
        "journal_quality_jufo": record.get("journalQualityJufo"),
        "relevance_notes": "Imported from Amass MCP output; relevance requires evidence extraction review.",
    }
    source["exercise_match"] = classify_exercise_match(source, entry)
    return source


def source_dedupe_key(source: dict[str, Any]) -> str:
    for field in ("pmid", "doi", "pmcid"):
        value = source.get(field)
        if value:
            return f"{field}:{str(value).lower()}"
    title = normalize_title(source.get("title") or "")
    if title:
        return f"title:{title}"
    digest = hashlib.sha1(json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def merge_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        key = source_dedupe_key(source)
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(source)
            continue
        backends = set(existing.get("source_backends") or [])
        backends.update(source.get("source_backends") or [source.get("backend")])
        existing["source_backends"] = sorted(backend for backend in backends if backend)
        existing["backend"] = "merged" if len(existing["source_backends"]) > 1 else existing.get("backend")
        for field, value in source.items():
            if field in {"source_id", "backend", "source_backends"}:
                continue
            if not existing.get(field) and value:
                existing[field] = value
        existing["has_fulltext"] = bool(existing.get("has_fulltext") or source.get("has_fulltext"))
        existing["is_retracted"] = bool(existing.get("is_retracted") or source.get("is_retracted"))

    ordered = sorted(
        merged.values(),
        key=lambda item: (
            item.get("is_retracted", False),
            item.get("exercise_match") != "direct",
            item.get("year") is None,
            -(item.get("year") or 0),
            item.get("title") or "",
        ),
    )
    for index, source in enumerate(ordered, start=1):
        source["source_id"] = f"SRC-{index:03d}"
    return ordered


def source_id_list(sources: list[dict[str, Any]]) -> list[str]:
    return [source["source_id"] for source in sources if source.get("source_id")]


def evidence_claim(
    claim: str,
    evidence_type: str = "unavailable",
    confidence: str = "unknown",
    confidence_score: float | None = None,
    source_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "claim": claim,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "source_ids": source_ids or [],
    }


def build_staged_draft_card(entry: ExerciseEntry, sources: list[dict[str, Any]]) -> dict[str, Any]:
    all_source_ids = source_id_list(sources)
    source_count = len(sources)
    summary_claim = evidence_claim(
        claim=(
            f"Для упражнения собран черновой список источников: {source_count}. "
            "Биомеханическое извлечение фактов еще не выполнено."
        ),
        evidence_type="unavailable",
        confidence="unknown",
        confidence_score=None,
        source_ids=all_source_ids,
    )
    return {
        "id": entry.exercise_id,
        "type": "exercise_card",
        "status": "staged_draft",
        "schema_version": "0.1.0",
        "language": "ru",
        "names": {"ru": entry.russian_name, **({"en": entry.exercise_name} if looks_english(entry.exercise_name) else {})},
        "aliases": entry.aliases,
        "exercise_name": entry.exercise_name,
        "russian_name": entry.russian_name,
        "exercise_id": entry.exercise_id,
        "exercise_family": "unclear",
        "variation": "standard",
        "variation_of": None,
        "related_variations": [],
        "category": "unclear",
        "body_region": "unclear",
        "target_region": "unclear",
        "dominance_type": "unclear",
        "modality": "unclear",
        "equipment_required": [],
        "compound_type": "unclear",
        "movement_patterns": ["unclear"],
        "force_vector": "unclear",
        "kinetic_chain": "unclear",
        "movement_planes": ["unclear"],
        "body_position": "unclear",
        "limb_pattern": "unclear",
        "technical_complexity": "unclear",
        "mobility_requirements": [],
        "movement_pattern_details": [],
        "primary_muscles": [],
        "secondary_muscles": [],
        "stabilizers": [],
        "joint_actions": [],
        "contraction_phase_emphasis": "unclear",
        "stimulus_phase_bias": "unclear",
        "muscle_stimulus_phase_bias": [],
        "resistance_profile": {
            "profile_type": "unclear",
            "peak_loading_region": "unclear",
            "explanation": "Не заполнено на этапе source-staging.",
            "evidence_type": "unavailable",
            "confidence": "unknown",
            "confidence_score": None,
            "assumptions": [],
            "source_ids": [],
        },
        "relative_muscle_emphasis": [],
        "fatigue_cost": {
            "local_fatigue": "unclear",
            "systemic_fatigue": "unclear",
            "technical_fatigue": "unclear",
            "axial_loading": "unclear",
            "stability_demand": "unclear",
            "overall_fatigue_cost": "unclear",
            "evidence_type": "unavailable",
            "confidence": "unknown",
            "confidence_score": None,
            "assumptions": [],
            "source_ids": [],
        },
        "sfr": {
            "sfr_class": "unclear",
            "evidence_type": "unavailable",
            "confidence": "unknown",
            "confidence_score": None,
            "context": "Не заполнено на этапе source-staging.",
            "assumptions": [],
            "source_ids": [],
        },
        "biomechanics": {
            "movement_phases": [],
            "joint_mechanics": [],
            "muscle_roles_by_phase": [],
            "external_load_mechanics": {
                "external_resistance_type": "unclear",
                "line_of_force": "unclear",
                "load_placement": "unclear",
                "main_moment_arms": [],
                "vector_shift_effects": [],
                "evidence_type": "unavailable",
                "confidence": "unknown",
                "source_ids": [],
            },
            "technique_variables": [],
            "biomechanical_summary": summary_claim,
        },
        "common_errors": [],
        "execution_steps": {
            "setup": [],
            "execution": [],
            "rom": [],
            "breathing_bracing": [],
            "tempo_control": [],
        },
        "best_use": {},
        "typical_rep_ranges": [],
        "progression_options": [],
        "when_to_avoid_or_modify": [],
        "prerequisite_skill_mobility": [],
        "supersets_trisets": [],
        "variations": [],
        "alternatives": [],
        "safety": {},
        "assumptions": [
            "Карточка создана как staged_draft: источники собраны, но биомеханические факты еще не извлечены."
        ],
        "limitations": [
            "На этом этапе карточка не содержит финальной биомеханической интерпретации.",
            "Если упражнение было указано только на русском языке без английского alias, PubMed-поиск может быть неполным."
        ],
        "not_supported_claims": [],
        "evidence_summary": {
            "source_count": source_count,
            "direct_match_count": sum(1 for source in sources if source.get("exercise_match") == "direct"),
            "fulltext_count": sum(1 for source in sources if source.get("has_fulltext")),
            "retracted_count": sum(1 for source in sources if source.get("is_retracted")),
            "backends": sorted({backend for source in sources for backend in source.get("source_backends", [])}),
        },
        "evidence_ledger": [summary_claim],
        "metadata": {
            "generated_at": now_iso(),
            "generator": "pipeline/generate_cards.py",
            "schema_version": "0.1.0",
        },
    }


def load_schema_registry() -> tuple[type[Any], Any, Any]:
    try:
        import jsonschema
        from referencing import Registry, Resource
    except ImportError as exc:
        raise PipelineError("jsonschema and referencing are required for validation.") from exc

    schema_root = PROJECT_ROOT / "schemas"
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    resources = []
    for path in [SCHEMA_PATH, *sorted((schema_root / "taxonomies").glob("*.json"))]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in data:
            resources.append((data["$id"], Resource.from_contents(data)))
        resources.append((path.relative_to(schema_root).as_posix(), Resource.from_contents(data)))

    registry = Registry().with_resources(resources)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls, schema, registry


def validate_card(card: dict[str, Any]) -> None:
    validator_cls, schema, registry = load_schema_registry()
    validator = validator_cls(schema, registry=registry)
    validator.validate(card)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process_exercise(entry: ExerciseEntry, args: argparse.Namespace) -> dict[str, Any]:
    output_root = PROJECT_ROOT / "output"
    log_dir = output_root / "logs" / entry.exercise_id
    log_dir.mkdir(parents=True, exist_ok=True)

    sources: list[dict[str, Any]] = []
    backend_logs = []
    amass_sources, amass_logs = load_amass_sources(args.amass_json, entry)
    sources.extend(amass_sources)
    backend_logs.extend(amass_logs)
    if not amass_sources:
        raise PipelineError(
            f"Amass source branch is mandatory for {entry.exercise_id}, "
            "but no Amass sources were loaded."
        )

    try:
        ncbi_sources, ncbi_log = run_ncbi_source_branch(entry, log_dir=log_dir, retmax=args.retmax)
        sources.extend(ncbi_sources)
        backend_logs.append(ncbi_log)
    except Exception as exc:
        backend_logs.append(
            {
                "backend": "ncbi_pubmed",
                "status": "error",
                "error": str(exc),
                "queries_used": build_pubmed_queries(entry),
            }
        )
        raise PipelineError(f"NCBI/PubMed source branch failed for {entry.exercise_id}: {exc}") from exc

    merged_sources = merge_sources(sources)
    card = build_staged_draft_card(entry, merged_sources)

    if not args.no_validate:
        validate_card(card)

    source_ledger = {
        "exercise_id": entry.exercise_id,
        "exercise_name": entry.exercise_name,
        "russian_name": entry.russian_name,
        "aliases": entry.aliases,
        "generated_at": now_iso(),
        "search_backends": backend_logs,
        "sources": merged_sources,
    }
    generation_log = {
        "exercise_id": entry.exercise_id,
        "generated_at": now_iso(),
        "card_path": str(output_root / "exercise_cards" / f"{entry.exercise_id}.json"),
        "sources_path": str(output_root / "sources" / f"{entry.exercise_id}.sources.json"),
        "source_count": len(merged_sources),
        "validation": "skipped" if args.no_validate else "passed",
        "backend_logs": backend_logs,
    }

    write_json(output_root / "exercise_cards" / f"{entry.exercise_id}.json", card)
    write_json(output_root / "sources" / f"{entry.exercise_id}.sources.json", source_ledger)
    write_json(output_root / "logs" / f"{entry.exercise_id}.log.json", generation_log)
    return generation_log


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate staged exercise-card drafts.")
    parser.add_argument("input_file", type=Path, help="Path to .txt, .md, or .csv input file.")
    parser.add_argument("--retmax", type=int, default=10, help="Maximum PubMed results per exercise.")
    parser.add_argument(
        "--amass-json",
        type=Path,
        action="append",
        required=True,
        help=(
            "Required Amass MCP search result JSON to merge. Supports either "
            "{'results': [...]} or {exercise_id: {'results': [...]}}."
        ),
    )
    parser.add_argument("--no-validate", action="store_true", help="Do not validate generated cards against JSON Schema.")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    input_file = args.input_file
    if not input_file.is_absolute():
        input_file = PROJECT_ROOT / input_file
    if not input_file.exists():
        parser.error(f"Input file not found: {input_file}")

    exercises = load_exercises(input_file)
    if not exercises:
        parser.error(f"No exercises found in input file: {input_file}")

    logs = []
    for entry in exercises:
        logs.append(process_exercise(entry, args))

    report = {
        "generated_at": now_iso(),
        "input_file": str(input_file),
        "exercise_count": len(exercises),
        "logs": logs,
    }
    write_json(PROJECT_ROOT / "output" / "logs" / "generation_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
