"""Synchronous, standalone AI entry point agreed with the backend team."""
from __future__ import annotations

import os
from time import perf_counter
from collections.abc import Callable

from . import prompts
from .critic import review_evidence, select_evidence
from .dialogue import normalize_turn
from .facts import update_facts
from .generation import generate_answer, semantic_review, usable_hits
from .llm import ChatClient, LLMConfig, LLMError
from .planner import make_plan
from .retriever import Retriever, configured_retriever
from .schemas import Stage, TurnResult
from .topics import identify_topic


def answer_turn(
    message: str,
    history: list[dict],
    session_facts: dict,
    debug: bool = False,
) -> dict:
    """Answer one turn without storing session data or creating a lead.

    Explicit customer industry/goal are merged into a deep-copied full snapshot.
    Default mode is extractive. AI_MODE=llm explicitly enables model API calls.
    Invalid input/configuration raises an exception for the caller to handle.
    """
    mode = os.getenv("AI_MODE", "extractive").strip() or "extractive"
    return _answer_turn(
        message, history, session_facts, debug,
        mode=mode, retriever_provider=configured_retriever,
    )


def _answer_turn(
    message: str,
    history: list[dict],
    session_facts: dict,
    debug: bool,
    *,
    mode: str,
    retriever_provider: Callable[[], Retriever | None],
    top_k: int = 8,
) -> dict:
    """Shared core with per-call dependencies, without process-env mutation."""
    started = perf_counter()
    if mode not in {"extractive", "llm"}:
        raise ValueError("AI_MODE must be extractive or llm")
    if not isinstance(session_facts, dict):
        raise TypeError("session_facts must be a dictionary")
    if not isinstance(debug, bool):
        raise TypeError("debug must be a boolean")
    current, turns = normalize_turn(message, history)
    plan = make_plan(current, turns)
    facts = update_facts(current, turns, session_facts)
    diagnostics = {"mode": "offline_extractive", "reason": plan.reason, "critic": "not_needed"}

    def finish(
        answer: str,
        stage: Stage,
        route: str,
        source_ids: list[str] | None = None,
        offer: bool = False,
    ) -> dict:
        diagnostics["latency_ms"] = round((perf_counter() - started) * 1000, 3)
        result: TurnResult = {
            "answer": answer,
            "stage": stage,
            "source_ids": source_ids or [],
            "route": route,
            "updated_facts": facts,
            "proposed_action": "offer_lead" if offer else None,
            "debug": diagnostics if debug else None,
        }
        return result

    if plan.route == "handoff":
        return finish(prompts.HANDOFF, "handoff", "handoff", offer=True)
    if plan.route == "scope":
        answer = prompts.OUT_OF_SCOPE
        if not plan.contact_declined:
            answer += " " + prompts.OFFER_SPECIALIST
        return finish(answer, "handoff", "handoff", offer=not plan.contact_declined)
    if plan.route == "simple":
        return finish(prompts.DISCOVER, "discover", "simple")
    if plan.route == "clarify":
        return finish(prompts.CLARIFY, "qualify", "clarify")

    retriever = retriever_provider()
    if retriever is None:
        diagnostics["knowledge"] = "not_configured"
        answer = prompts.NO_KNOWLEDGE
        if plan.contact_declined:
            answer = prompts.REFUSAL_ACK + " " + answer
        return finish(answer, "discover", "simple")

    hits = retriever.search(plan.query, top_k=top_k, topic=plan.topic)
    if mode == "llm" and usable_hits(hits):
        # Missing explicit configuration must not masquerade as a tested model.
        client = ChatClient(LLMConfig.from_env())
        diagnostics["mode"] = "llm"
        diagnostics["response_mode"] = "extractive_fallback"
        try:
            draft = generate_answer(client, current, turns, facts, hits, plan.contact_declined)
            verdict = semantic_review(client, current, turns, facts, draft, hits, plan.contact_declined)
            diagnostics["generation"] = {
                "status": "approved" if verdict.approved else "semantic_rejected",
                "semantic_checks": verdict.checks(),
            }
            if verdict.approved:
                diagnostics.update({
                    "response_mode": "generated", "critic": "semantic_passed", "topic": plan.topic,
                    "retrieved_chunk_ids": [hit.chunk.chunk_id for hit in hits],
                    "used_chunk_ids": [hit.chunk.chunk_id for hit in usable_hits(hits)
                                       if hit.chunk.source_id in draft.source_ids],
                })
                return finish(draft.answer, "qualify", "rag", source_ids=list(draft.source_ids))
        except LLMError as exc:
            # Only local error codes reach debug; never copy API bodies or prompts.
            diagnostics["generation"] = {"status": "failed", "error": str(exc)}
    evidence_query = current if identify_topic(current) else plan.query
    evidence = select_evidence(
        evidence_query, hits, term_weights=retriever.query_weights(evidence_query),
        avoid_contact=plan.contact_declined,
    )
    review = review_evidence(evidence, hits)
    diagnostics.update({
        "knowledge": "configured",
        "retrieved_chunk_ids": [hit.chunk.chunk_id for hit in hits],
        "used_chunk_ids": [item.chunk_id for item in evidence] if review.approved else [],
        "critic": review.reason,
        "risk_check": plan.risky,
        "topic": plan.topic,
    })
    if not review.approved:
        answer = prompts.NOT_FOUND
        if plan.contact_declined:
            answer = prompts.REFUSAL_ACK + " " + answer + " " + prompts.CLARIFY
            return finish(answer, "qualify", "clarify")
        return finish(answer + " " + prompts.OFFER_SPECIALIST, "handoff", "handoff", offer=True)

    answer = prompts.EVIDENCE_PREFIX + "\n\n" + "\n\n".join(item.text for item in evidence)
    used_heading = next(hit.chunk.heading for hit in hits if hit.chunk.chunk_id == evidence[0].chunk_id)
    leaf_heading = used_heading.split(" / ")[-1]
    if "не подходит" in leaf_heading.lower() or "не делаем" in leaf_heading.lower():
        answer = prompts.EVIDENCE_PREFIX + f"\n\n{leaf_heading}:\n" + evidence[0].text
    if plan.risky:
        answer += "\n\n" + prompts.RISK_CAVEAT
    if plan.contact_declined:
        answer = prompts.REFUSAL_ACK + "\n\n" + answer
    sources = list(dict.fromkeys(item.source_id for item in evidence))
    return finish(answer, "qualify", "rag", source_ids=sources)
