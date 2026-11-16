"""Optional generation and independent semantic review via the same API.

Offline tests verify protocol handling and routing, not the model's ability to
judge meaning. A real model review can still be wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .llm import ChatClient, LLMError, json_object
from .prompts import GENERATION_SYSTEM, SEMANTIC_REVIEW_SYSTEM
from .schemas import SearchHit


@dataclass(frozen=True)
class Draft:
    answer: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticReview:
    grounded: bool
    relevant: bool
    context_consistent: bool
    safe_handoff: bool
    unsupported_claims: tuple[str, ...]
    reason: str

    @property
    def approved(self) -> bool:
        return (self.grounded and self.relevant and self.context_consistent
                and self.safe_handoff and not self.unsupported_claims)

    def checks(self) -> dict[str, bool]:
        return {name: getattr(self, name) for name in (
            "grounded", "relevant", "context_consistent", "safe_handoff",
        )}


def usable_hits(hits: list[SearchHit]) -> list[SearchHit]:
    return [hit for hit in hits if "чего утверждать нельзя" not in hit.chunk.heading.lower()][:6]


def _evidence(hits: list[SearchHit]) -> list[dict]:
    # Only the document identifier is a valid output citation. Exposing the
    # internal chunk_id alongside it makes small models cite the wrong field.
    return [{"source_id": hit.chunk.source_id, "heading": hit.chunk.heading,
             "text": hit.chunk.text} for hit in usable_hits(hits)]


def _messages(system: str, payload: dict) -> list[dict]:
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _numbers(text: str) -> set[str]:
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?:\D|$))", "", text)
    return {match.replace(",", ".") for match in re.findall(r"\d+(?:[.,]\d+)?", text)}


def generate_answer(
    client: ChatClient,
    message: str,
    history: list[dict],
    session_facts: dict,
    hits: list[SearchHit],
    contact_declined: bool,
) -> Draft:
    passages = _evidence(hits)
    if not passages:
        raise LLMError("no_generation_evidence")
    payload = {
        "message": message, "history": history[-12:], "session_facts": session_facts,
        "contact_declined": contact_declined, "evidence": passages,
    }
    response = json_object(client.complete(_messages(GENERATION_SYSTEM, payload)))
    if set(response) != {"answer", "source_ids"}:
        raise LLMError("invalid_generation_schema")
    answer, sources = response["answer"], response["source_ids"]
    if not isinstance(answer, str) or not answer.strip() or len(answer.split()) > 150:
        raise LLMError("invalid_generated_answer")
    if not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources):
        raise LLMError("invalid_generated_sources")
    allowed = {passage["source_id"] for passage in passages}
    if not set(sources) <= allowed:
        raise LLMError("unknown_generated_source")
    if re.search(r"заявк\w* (?:уже )?(?:создан|оформлен|отправлен)|(?:создал|оформил|отправил)\w* заявк", answer, re.I):
        raise LLMError("unauthorized_lead_claim")
    if contact_declined and re.search(
        r"(?:оставьте|укажите|пришлите|сообщите).{0,35}(?:телефон|контакт|номер)|свяжитесь", answer, re.I,
    ):
        raise LLMError("contact_refusal_ignored")
    support = " ".join(passage["text"] for passage in passages if passage["source_id"] in sources)
    # This only catches obviously new numerals; semantic review must check units,
    # subject, negation and caveats. User numbers cannot justify product prices.
    user_context = " ".join(item["content"] for item in history if item["role"] == "user")
    support += " " + message + " " + user_context + " " + json.dumps(session_facts, ensure_ascii=False)
    if not _numbers(answer) <= _numbers(support):
        raise LLMError("unsupported_generated_number")
    return Draft(answer.strip(), tuple(dict.fromkeys(sources)))


def semantic_review(
    client: ChatClient,
    message: str,
    history: list[dict],
    session_facts: dict,
    draft: Draft,
    hits: list[SearchHit],
    contact_declined: bool,
    reference_answer: str | None = None,
) -> SemanticReview:
    passages = _evidence([hit for hit in hits if hit.chunk.source_id in draft.source_ids])
    if not passages or set(draft.source_ids) != {passage["source_id"] for passage in passages}:
        raise LLMError("missing_review_evidence")
    payload = {
        "message": message, "history": history[-12:], "session_facts": session_facts,
        "answer": draft.answer, "source_ids": list(draft.source_ids),
        "cited_evidence": passages, "contact_declined": contact_declined,
    }
    if reference_answer is not None:
        payload["reference_answer"] = reference_answer
    result = json_object(client.complete(_messages(SEMANTIC_REVIEW_SYSTEM, payload), max_tokens=1000))
    boolean_fields = {"grounded", "relevant", "context_consistent", "safe_handoff"}
    if set(result) != boolean_fields | {"unsupported_claims", "reason"}:
        raise LLMError("invalid_semantic_schema")
    if any(type(result[field]) is not bool for field in boolean_fields):
        raise LLMError("invalid_semantic_schema")
    claims = result["unsupported_claims"]
    if (not isinstance(claims, list) or not all(isinstance(claim, str) for claim in claims)
            or not isinstance(result["reason"], str) or not result["reason"].strip()):
        raise LLMError("invalid_semantic_schema")
    return SemanticReview(**{field: result[field] for field in boolean_fields},
                          unsupported_claims=tuple(claims), reason=result["reason"])
