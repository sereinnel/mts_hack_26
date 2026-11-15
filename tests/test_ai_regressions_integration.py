"""Real AI -> existing HTTP adapter -> existing session-facts storage."""
from __future__ import annotations

import json
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend import db
from backend.main import app


def test_real_ai_fills_and_persists_customer_facts_and_routes_askue(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "regression.sqlite3"))
    monkeypatch.setenv("AI_FUNCTION", "ai.consultant:answer_turn")
    monkeypatch.setenv("AI_MODE", "extractive")
    monkeypatch.delenv("AI_INDEX_PATH", raising=False)
    archive = tmp_path / "knowledge-base.zip"
    with ZipFile(archive, "w") as stream:
        stream.writestr("synthetic/platform.md", "# Облачная платформа учёта электроэнергии\n\n"
                        "## Что это\n\nПлатформа собирает показания тестовых приборов и отображает потребление.")
        stream.writestr("synthetic/losses.md", "# Поиск коммерческих потерь\n\n"
                        "Решение решает задачи на предприятии и выявляет коммерческие потери.")
    monkeypatch.setenv("AI_KB_PATH", str(archive))

    with TestClient(app) as client:
        session_id = client.post("/api/sessions").json()["id"]
        response = client.post("/api/chat", json={
            "session_id": session_id,
            "message": "У нас производственное предприятие. Хотим снизить расходы на электричество",
        })
        assert response.status_code == 200, response.text
        expected = {"industry": "manufacturing", "goal": "reduce_energy_costs"}
        assert db.get_session_facts(session_id) == expected
        with db.connection() as connection:
            row = connection.execute("SELECT facts_json FROM session_facts WHERE session_id=?", (session_id,)).fetchone()
        assert json.loads(row["facts_json"]) == expected

        response = client.post("/api/chat", json={"session_id": session_id, "message": "Какие данные нужны?"})
        assert response.status_code == 200, response.text
        assert db.get_session_facts(session_id) == expected

        new_session = client.post("/api/sessions").json()["id"]
        response = client.post("/api/chat", json={
            "session_id": new_session,
            "message": "Что такое АСКУЭ и какие задачи она решает на предприятии?",
        })
        assert response.status_code == 200, response.text
        assert response.json()["sources"] == ["synthetic/platform.md"]
        assert "собирает показания" in response.json()["answer"]
        assert "коммерческие потери" not in response.json()["answer"]
        assert db.get_session_facts(new_session) == {}
        assert db.get_session_facts(session_id) == expected
        assert db.list_leads() == []
