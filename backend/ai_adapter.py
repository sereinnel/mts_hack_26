"""Call the agreed standalone AI entry point configured by AI_FUNCTION.

The module must export answer_turn(message, history, session_facts, debug=False).
The mock fallback is kept when AI_FUNCTION is not configured.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import os
from typing import Any


async def consult_ai(
    question: str, history: list[dict[str, str]], session_facts: dict | None = None,
    debug: bool = False,
) -> dict[str, Any]:
    target = os.getenv("AI_FUNCTION", "").strip()
    if not target:
        return {
            "answer": (
                "Это тестовый ответ backend. Подключите реальный RAG через "
                "переменную AI_FUNCTION. Пока я не могу рекомендовать продукты."
            ),
            "sources": [],
            "intent": "mock",
            "updated_facts": dict(session_facts or {}),
            "stage": None,
            "route": "mock",
            "proposed_action": None,
            "debug": None,
        }

    module_name, separator, function_name = target.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError("AI_FUNCTION must be module.path:function")
    func = getattr(importlib.import_module(module_name), function_name)
    # AI core remains independent from HTTP/SQLite; backend provides the facts.
    kwargs = {
        "message": question,
        "history": history,
        "session_facts": dict(session_facts or {}),
        "debug": debug,
    }
    if inspect.iscoroutinefunction(func):
        result = await func(**kwargs)
    else:
        result = await asyncio.to_thread(func, **kwargs)

    if isinstance(result, str):
        result = {"answer": result}
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not result["answer"].strip():
        raise ValueError("AI function must return dict with non-empty 'answer'")
    sources = result.get("source_ids", result.get("sources", [])) or []
    if not isinstance(sources, list):
        raise ValueError("AI function 'sources' must be a list")
    updated_facts = result.get("updated_facts", session_facts or {})
    if not isinstance(updated_facts, dict):
        raise ValueError("AI function 'updated_facts' must be a dictionary")
    return {
        "answer": result["answer"].strip(),
        "sources": [str(s) for s in sources],
        "intent": str(result.get("intent", "unknown")),
        "updated_facts": updated_facts,
        "stage": result.get("stage"),
        "route": result.get("route"),
        "proposed_action": result.get("proposed_action"),
        "debug": result.get("debug") if debug else None,
    }
