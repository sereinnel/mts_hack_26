"""Extractive grounding checks, not an LLM or a semantic fact checker."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re

from .retriever import words
from .schemas import Evidence, SearchHit


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _prohibited(heading: str) -> bool:
    return "чего утверждать нельзя" in heading.lower()


def select_evidence(
    query: str,
    hits: list[SearchHit],
    max_words: int = 105,
    term_weights: dict[str, float] | None = None,
    avoid_contact: bool = False,
) -> list[Evidence]:
    """Keep whole paragraphs, so sentence-level caveats are not truncated."""
    query_terms = term_weights if term_weights is not None else Counter(words(query))
    candidates = []
    for rank, hit in enumerate(hits):
        chunk = hit.chunk
        if _prohibited(chunk.heading):
            continue
        paragraphs = re.split(r"\n\s*\n", chunk.text)
        units = []
        for paragraph in paragraphs:
            if re.search(r"[-_]{5,}|\S {2,}\S", paragraph):
                continue
            # A list item is kept with all of its wrapped continuation lines.
            units.extend(re.split(r"\n(?=(?:-\s+|\d+\.\s+))", paragraph))
        heading_terms = set(words(chunk.heading.split(" / ")[-1]))
        for index, paragraph in enumerate(units):
            text = _normalize(paragraph)
            if not text or re.search(r"[-_]{5,}", text):
                continue  # Markdown/plain-text tables need a separate renderer.
            if text.endswith(":"):
                if index + 1 == len(units):
                    continue
                following = index + 1
                while following < len(units):
                    text += " " + _normalize(units[following])
                    following += 1
                    if following == len(units) or not re.match(r"^(?:-\s+|\d+\.\s+)", units[following]):
                        break
            if re.search(r"\[[^\]]+\]\(", text):
                continue  # Relative corpus links are not usable frontend URLs.
            if avoid_contact and re.search(
                r"остав\w*.{0,25}(?:заявк|контакт|телефон)|заполн\w*.{0,15}форм|свяжитесь", text, re.I,
            ):
                continue
            count = len(text.split())
            if count > max_words:
                continue
            if text not in _normalize(chunk.text):
                continue
            terms = set(words(text))
            overlap = sum(weight for term, weight in query_terms.items() if term in terms)
            heading_overlap = sum(weight for term, weight in query_terms.items() if term in heading_terms)
            if not overlap and not heading_overlap:
                continue
            score = (overlap + 0.8 * heading_overlap) / max(15, count) ** 0.15
            score *= 1 - 0.035 * rank
            candidates.append((score, chunk.chunk_id, text, Evidence(chunk.source_id, chunk.chunk_id, text)))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    # Return one coherent passage rather than stitching unrelated claims.
    return [candidates[0][3]] if candidates else []


@dataclass(frozen=True)
class Review:
    approved: bool
    reason: str


def review_evidence(evidence: list[Evidence], hits: list[SearchHit]) -> Review:
    if not evidence:
        return Review(False, "no_supported_passage")
    available = {hit.chunk.chunk_id: hit.chunk for hit in hits}
    for item in evidence:
        chunk = available.get(item.chunk_id)
        if chunk is None or chunk.source_id != item.source_id:
            return Review(False, "unknown_source")
        if _prohibited(chunk.heading):
            return Review(False, "prohibited_claim_section")
        if _normalize(item.text) not in _normalize(chunk.text):
            return Review(False, "passage_not_in_source")
    return Review(True, "extractive_grounding_passed")
