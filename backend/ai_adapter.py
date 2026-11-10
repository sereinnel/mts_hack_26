"""Replace mock via AI_FUNCTION='package.module:function'.

Expected synchronous or asynchronous function:
  consult(question: str, history: list[dict]) -> dict
The dict must contain a non-empty `answer`, optional `sources` and `intent`.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import os
from typing import Any


async def consult_ai(question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    target = os.getenv("AI_FUNCTION", "").strip()
    if not target:
        return {
            "answer": (
                "Это тестовый ответ backend. Подключите реальный RAG через "
                "переменную AI_FUNCTION. Пока я не могу рекомендовать продукты."
            ),
            "sources": [],
            "intent": "mock",
        }

    module_name, separator, function_name = target.partition(":")
    if not separator or not module_name or not function_name:
        raise ValueError("AI_FUNCTION must be module.path:function")
    func = getattr(importlib.import_module(module_name), function_name)
    if inspect.iscoroutinefunction(func):
        result = await func(question=question, history=history)
    else:
        result = await asyncio.to_thread(func, question=question, history=history)

    if isinstance(result, str):
        result = {"answer": result}
    if not isinstance(result, dict) or not isinstance(result.get("answer"), str) or not result["answer"].strip():
        raise ValueError("AI function must return dict with non-empty 'answer'")
    sources = result.get("sources", []) or []
    if not isinstance(sources, list):
        raise ValueError("AI function 'sources' must be a list")
    return {
        "answer": result["answer"].strip(),
        "sources": [str(s) for s in sources],
        "intent": str(result.get("intent", "unknown")),
    }
