"""Persist the complete AI facts snapshot between chat turns and isolate sessions."""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend import db
from backend.main import app


def test_facts_are_persisted_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "session_facts.sqlite3"))
    snapshots = []

    async def fake_ai(message, history, session_facts):
        snapshots.append(dict(session_facts))
        return {
            "answer": f"Получено: {message}",
            "sources": [],
            "intent": "unknown",
            "updated_facts": {**session_facts, "last_question": message},
            "stage": "qualify",
        }

    monkeypatch.setattr("backend.main.consult_ai", fake_ai)
    with TestClient(app) as client:
        first = client.post("/api/sessions").json()["id"]
        second = client.post("/api/sessions").json()["id"]

        response = client.post("/api/chat", json={"session_id": first, "message": "Вопрос 1"})
        assert response.status_code == 200, response.text
        assert db.get_session_facts(first) == {"last_question": "Вопрос 1"}
        assert snapshots[-1] == {}

        response = client.post("/api/chat", json={"session_id": first, "message": "Вопрос 2"})
        assert response.status_code == 200, response.text
        assert snapshots[-1] == {"last_question": "Вопрос 1"}
        assert db.get_session_facts(first) == {"last_question": "Вопрос 2"}

        response = client.post("/api/chat", json={"session_id": second, "message": "Другая сессия"})
        assert response.status_code == 200, response.text
        assert snapshots[-1] == {}
        assert db.get_session_facts(second) == {"last_question": "Другая сессия"}
        assert db.get_session_facts(first) == {"last_question": "Вопрос 2"}


def test_facts_remain_empty_if_ai_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "failed_turn.sqlite3"))

    async def failing_ai(message, history, session_facts):
        raise RuntimeError("test AI failure")

    monkeypatch.setattr("backend.main.consult_ai", failing_ai)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response = client.post("/api/chat", json={"session_id": session_id, "message": "Тест"})
        assert response.status_code == 502
        assert db.get_session_facts(session_id) == {}


def test_adapter_passes_facts_to_ai(monkeypatch):
    import asyncio
    import ai.consultant
    from backend.ai_adapter import consult_ai

    def fake_answer_turn(message, history, session_facts, debug):
        assert message == "Здравствуйте"
        assert history == []
        assert session_facts == {"industry": "manufacturing"}
        assert debug is False
        return {
            "answer": "Принято",
            "source_ids": [],
            "stage": "qualify",
            "updated_facts": {"industry": "manufacturing", "topic": "electricity"},
        }

    monkeypatch.setenv("AI_FUNCTION", "ai.consultant:answer_turn")
    monkeypatch.setattr(ai.consultant, "answer_turn", fake_answer_turn)
    result = asyncio.run(consult_ai("Здравствуйте", [], {"industry": "manufacturing"}))
    assert result["updated_facts"] == {
        "industry": "manufacturing", "topic": "electricity"
    }
    assert result["stage"] == "qualify"
