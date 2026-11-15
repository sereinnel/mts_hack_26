"""Competition AI callable; CSV processing and ZIP packaging belong to backend."""
from __future__ import annotations

import os
from pathlib import Path

from .consultant import _answer_turn
from .retriever import retriever_from_path

__all__ = ["answer_question"]


def answer_question(question: str, knowledge_base: str | Path) -> str:
    """Return answer text for one independent question or embedded dialogue.

    The explicit corpus path overrides all web-app AI path settings. Model mode
    is enabled for this call without changing AI_MODE or other environment vars.
    Only immutable corpus data are cached; no case history/facts are retained.
    """
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    if not question.strip():
        raise ValueError("question must not be empty")
    raw_top_k = os.getenv("TOP_K", "8").strip()
    if not raw_top_k or raw_top_k == "TOP_K":
        raw_top_k = "8"
    try:
        top_k = int(raw_top_k)
    except ValueError:
        raise ValueError("TOP_K must be an integer in [1, 30]") from None
    if not 1 <= top_k <= 30:
        raise ValueError("TOP_K must be an integer in [1, 30]")
    retriever = retriever_from_path(knowledge_base)
    result = _answer_turn(
        question, [], {}, False,
        mode="llm", retriever_provider=lambda: retriever, top_k=top_k,
    )
    return " ".join(result["answer"].split())
