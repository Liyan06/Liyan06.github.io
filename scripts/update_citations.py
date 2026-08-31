#!/usr/bin/env python3
"""Refresh publication citation counts from the SerpAPI Google Scholar API."""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AUTHOR_ID = "P3dSamwAAAAJ"
API_URL = "https://serpapi.com/search"
ROOT = Path(__file__).resolve().parents[1]
COUNTS_PATH = ROOT / "_data" / "citations.yml"

PAPERS = {
    "wikiskill": "WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution",
    "vrrl": "Visually Grounded Self-Reflection for Vision-Language Models via Reinforcement Learning",
    "chartmuseum": "ChartMuseum: Testing Visual Reasoning Capabilities of Large Vision-Language Models",
    "minicheck": "MiniCheck: Efficient Fact-Checking of LLMs on Grounding Documents",
    "tofueval": "TofuEval: Evaluating Hallucinations of LLMs on Topic-Focused Dialogue Summarization",
    "factual_errors": "Understanding Factual Errors in Summarization: Errors, Summarizers, Datasets, Error Detectors",
    "medical_evidence": "Evaluating Large Language Models on Medical Evidence Summarization",
}


def normalize_title(title: str) -> str:
    """Normalize punctuation, accents, whitespace, and case for title matching."""
    decomposed = unicodedata.normalize("NFKD", title).casefold()
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[^\W_]+", without_marks, flags=re.UNICODE))


def parse_count(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, str):
        compact = value.replace(",", "").strip()
        if compact.isdigit():
            return int(compact)
    return None


def fetch_author_payload(api_key: str) -> dict[str, object]:
    query = urlencode(
        {
            "engine": "google_scholar_author",
            "author_id": AUTHOR_ID,
            "hl": "en",
            "num": 100,
            "api_key": api_key,
        }
    )
    request = Request(
        f"{API_URL}?{query}",
        headers={"User-Agent": "Liyan06.github.io citation updater"},
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"SerpAPI returned HTTP {error.code}.") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not reach SerpAPI: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("SerpAPI returned invalid JSON.") from error

    if not isinstance(payload, dict):
        raise RuntimeError("SerpAPI returned an unexpected response.")
    if payload.get("error"):
        raise RuntimeError(f"SerpAPI error: {payload['error']}")
    return payload


def extract_counts(payload: dict[str, object]) -> dict[str, int]:
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise RuntimeError("SerpAPI response did not contain an articles list.")

    titles_to_ids = {
        normalize_title(title): paper_id for paper_id, title in PAPERS.items()
    }
    counts: dict[str, int] = {}

    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get("title"), str):
            continue
        paper_id = titles_to_ids.get(normalize_title(article["title"]))
        if paper_id is None:
            continue

        cited_by = article.get("cited_by")
        if not isinstance(cited_by, dict):
            continue
        count = parse_count(cited_by.get("value"))
        if count is not None:
            counts[paper_id] = max(counts.get(paper_id, 0), count)

    if not counts:
        raise RuntimeError("None of the selected publication titles matched SerpAPI.")
    return counts


def load_existing_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}

    counts: dict[str, int] = {}
    pattern = re.compile(r"^([a-z0-9_]+):\s*([0-9]+)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            counts[match.group(1)] = int(match.group(2))
    return counts


def write_counts(path: Path, counts: dict[str, int]) -> None:
    rendered = "".join(f"{paper_id}: {counts[paper_id]}\n" for paper_id in PAPERS)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        print("Citation counts are already current.")
        return

    temporary_path = path.with_suffix(".yml.tmp")
    temporary_path.write_text(rendered, encoding="utf-8")
    temporary_path.replace(path)
    print(f"Updated {path.relative_to(ROOT)}.")


def main() -> int:
    api_key = os.environ.get("SERPAPI_KEY", "").strip()
    if not api_key:
        print("SERPAPI_KEY is required.", file=sys.stderr)
        return 1

    try:
        live_counts = extract_counts(fetch_author_payload(api_key))
        existing_counts = load_existing_counts(COUNTS_PATH)
        merged_counts = {
            paper_id: live_counts.get(paper_id, existing_counts.get(paper_id, 0))
            for paper_id in PAPERS
        }

        missing = [paper_id for paper_id in PAPERS if paper_id not in live_counts]
        if missing:
            print(
                "No matching Scholar article for: " + ", ".join(missing)
                + "; preserving existing values.",
                file=sys.stderr,
            )

        write_counts(COUNTS_PATH, merged_counts)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
