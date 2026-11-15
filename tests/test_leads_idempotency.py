"""Lead submission is safe to retry and never overwrites contact information."""

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from backend import db
from backend.main import app


def _payload(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "full_name": "Иван Иванов",
        "phone": "+79990000000",
        "company": "ООО Тест",
        "consent_to_contact": True,
    }


def test_duplicate_lead_reuses_original_id_and_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret")
    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = _payload(sid)
        first = client.post("/api/leads", json=payload)
        assert first.status_code == 201, first.text
        second = client.post("/api/leads", json=payload)
        assert second.status_code == 200, second.text
        assert second.json() == first.json()
        listed = client.get("/api/leads", headers={"X-Admin-Token": "test-secret"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_changed_contact_conflicts_without_overwriting_or_bypassing_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    monkeypatch.setenv("ADMIN_TOKEN", "test-secret")
    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        payload = _payload(sid)
        first = client.post("/api/leads", json=payload)
        assert first.status_code == 201

        changed = {**payload, "phone": "+79990000001"}
        assert client.post("/api/leads", json=changed).status_code == 409
        assert client.post("/api/leads", json={**payload, "consent_to_contact": False}).status_code == 400
        listed = client.get("/api/leads", headers={"X-Admin-Token": "test-secret"}).json()
        assert len(listed) == 1
        assert listed[0]["phone"] == payload["phone"]

        next_sid = client.post("/api/sessions").json()["id"]
        next_lead = client.post("/api/leads", json=_payload(next_sid))
        assert next_lead.status_code == 201
        assert next_lead.json()["id"] != first.json()["id"]


def test_concurrent_lead_creation_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "leads.sqlite3"))
    db.init_db()
    sid = db.create_session()["id"]

    def submit(_):
        return db.create_lead(sid, "Иван Иванов", "+79990000000", "ООО Тест", "test summary")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(submit, range(8)))
    assert len({lead["id"] for lead, _created in results}) == 1
    assert sum(created for _lead, created in results) == 1
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM leads WHERE session_id=?", (sid,)).fetchone()[0] == 1
