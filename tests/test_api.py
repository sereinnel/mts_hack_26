import os

from fastapi.testclient import TestClient

os.environ["DATABASE_PATH"] = "./data/test_energytool.sqlite3"
from backend.main import app  # noqa: E402


def test_chat_lead_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    with TestClient(app) as client:
        assert client.get("/health").json()["ai_mode"] == "mock"
        first = client.post("/api/sessions").json()["id"]
        reply = client.post("/api/chat", json={"session_id": first, "message": "Нужен учёт"})
        assert reply.status_code == 200, reply.text
        assert reply.json()["intent"] == "mock"
        history = client.get(f"/api/sessions/{first}/messages").json()
        assert [m["role"] for m in history] == ["user", "assistant"]
        lead = client.post("/api/leads", json={"session_id":first,"full_name":"Тест Тестов", "phone":"+70000000000", "company":"Тестовая компания", "consent_to_contact":True})
        assert lead.status_code == 201, lead.text
        assert "Тестовая компания" in lead.json()["summary"]
        assert client.get("/api/leads").status_code == 503
        monkeypatch.setenv("ADMIN_TOKEN", "secret")
        assert client.get("/api/leads", headers={"X-Admin-Token":"secret"}).status_code == 200
        assert client.post(f"/api/sessions/{first}/close").status_code == 200
        assert client.post("/api/chat", json={"session_id":first,"message":"test"}).status_code == 404
        second = client.post("/api/sessions").json()["id"]
        assert second != first
        assert client.get(f"/api/sessions/{second}/messages").json() == []
        assert len(client.get(f"/api/sessions/{first}/messages").json()) == 2
