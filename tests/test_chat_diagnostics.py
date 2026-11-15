"""Diagnostic response metadata is optional and available only to admins."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from backend.main import app


def test_chat_metadata_and_existing_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "normal.sqlite3"))
    async def fake_ai(message, history, session_facts):
        return {
            "answer": "Доступна система учёта", "sources": ["20-products/22-askue.md"],
            "intent": "question", "updated_facts": {}, "stage": "recommend",
            "route": "rag", "proposed_action": "offer_lead", "debug": {"hidden": True},
        }
    monkeypatch.setattr("backend.main.consult_ai", fake_ai)
    with TestClient(app) as client:
        session = client.post("/api/sessions").json()["id"]
        response = client.post("/api/chat", json={"session_id": session, "message": "Про учёт"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["answer"] == "Доступна система учёта"
        assert data["sources"] == data["source_ids"] == ["20-products/22-askue.md"]
        assert data["stage"] == "recommend"
        assert data["route"] == "rag"
        assert data["suggested_action"] == "offer_lead"
        assert isinstance(data["latency_ms"], int)
        assert "diagnostics" not in data
        assert len(client.get(f"/api/sessions/{session}/messages").json()) == 2


def test_debug_requires_server_admin_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "protected.sqlite3"))
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    with TestClient(app) as client:
        session = client.post("/api/sessions").json()["id"]
        debug_query = {"session_id": session, "message": "Диагностика", "debug": True}
        assert client.post("/api/chat", json=debug_query).status_code == 503
        monkeypatch.setenv("ADMIN_TOKEN", "safe-test-secret")
        assert client.post("/api/chat", json=debug_query).status_code == 403
        assert client.post("/api/chat", json=debug_query,
                           headers={"X-Admin-Token": "wrong"}).status_code == 403
        assert client.get(f"/api/sessions/{session}/messages").json() == []


def test_debug_passed_to_ai_and_returned_only_to_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "debug.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", "safe-test-secret")
    async def fake_ai(message, history, session_facts, *, debug):
        assert debug is True
        return {
            "answer": "Найден релевантный документ", "sources": ["20-products/22-askue.md"],
            "intent": "question", "updated_facts": {}, "stage": "qualify", "route": "rag",
            "proposed_action": None, "debug": {"used_chunk_ids": ["askue-1"], "critic": "passed"},
        }
    monkeypatch.setattr("backend.main.consult_ai", fake_ai)
    with TestClient(app) as client:
        session = client.post("/api/sessions").json()["id"]
        response = client.post("/api/chat",
                               json={"session_id": session, "message": "АСКУЭ", "debug": True},
                               headers={"X-Admin-Token": "safe-test-secret"})
        assert response.status_code == 200, response.text
        assert response.json()["diagnostics"] == {"used_chunk_ids": ["askue-1"], "critic": "passed"}


def test_adapter_forwards_debug_to_ai(monkeypatch):
    import ai.consultant
    from backend.ai_adapter import consult_ai

    def fake_answer_turn(message, history, session_facts, debug=False):
        assert debug is True
        return {
            "answer": "Ответ", "source_ids": ["demo.md"], "stage": "recommend",
            "route": "rag", "updated_facts": session_facts,
            "proposed_action": "offer_lead", "debug": {"mode": "offline_extractive"},
        }
    monkeypatch.setenv("AI_FUNCTION", "ai.consultant:answer_turn")
    monkeypatch.setattr(ai.consultant, "answer_turn", fake_answer_turn)
    result = asyncio.run(consult_ai("Вопрос", [], debug=True))
    assert result["sources"] == ["demo.md"]
    assert result["route"] == "rag"
    assert result["proposed_action"] == "offer_lead"
    assert result["debug"] == {"mode": "offline_extractive"}
