"""Smoke check for the independent, in-process AI core."""
from __future__ import annotations

import asyncio
from zipfile import ZipFile

from backend.ai_adapter import consult_ai


def test_real_ai_contract_without_external_llm(tmp_path, monkeypatch):
    kb = tmp_path / "knowledge-base.zip"
    with ZipFile(kb, "w") as archive:
        archive.writestr(
            "demo.md",
            "# Учет электроэнергии\n\nДля предприятий можно использовать "
            "автоматизированный учёт электрической энергии.\n",
        )
    monkeypatch.setenv("AI_FUNCTION", "ai.consultant:answer_turn")
    monkeypatch.setenv("AI_KB_PATH", str(kb))
    monkeypatch.delenv("AI_INDEX_PATH", raising=False)
    monkeypatch.setenv("AI_MODE", "extractive")
    result = asyncio.run(consult_ai("Как организовать учёт электроэнергии?", []))
    assert result["answer"].strip()
    assert result["intent"] == "unknown"
    assert isinstance(result["sources"], list)
    assert "тестовый ответ backend" not in result["answer"].lower()
