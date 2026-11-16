"""Two real AI turns must not overwrite each other's session-facts snapshots."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from threading import Event

from fastapi.testclient import TestClient

from backend import db
from backend.main import app
from backend.ai_adapter import consult_ai as real_consult_ai


def test_concurrent_chat_turns_preserve_both_customer_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "concurrent.sqlite3"))
    monkeypatch.setenv("AI_FUNCTION", "ai.consultant:answer_turn")
    monkeypatch.setenv("AI_MODE", "extractive")
    monkeypatch.setenv("AI_KB_PATH", "")
    monkeypatch.setenv("AI_INDEX_PATH", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    first_ready = Event()
    release_first = Event()

    async def delayed_ai(message, history, session_facts, **kwargs):
        result = await real_consult_ai(message, history, session_facts, **kwargs)
        if message == "У нас завод.":
            first_ready.set()
            if not await asyncio.to_thread(release_first.wait, 10):
                raise TimeoutError("test did not release first turn")
        return result

    monkeypatch.setattr("backend.main.consult_ai", delayed_ai)
    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["id"]
        other_sid = client.post("/api/sessions").json()["id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.post, "/api/chat", json={"session_id": sid, "message": "У нас завод."})
            try:
                assert first_ready.wait(5), "first AI turn did not start"
                independent = pool.submit(client.post, "/api/chat", json={
                    "session_id": other_sid, "message": "Привет",
                }).result(timeout=2)
                assert independent.status_code == 200, independent.text
                assert not first.done(), "an independent session must not wait for the first AI call"
                second = pool.submit(client.post, "/api/chat", json={
                    "session_id": sid, "message": "Хотим снизить расходы на электричество.",
                })
                try:
                    # An implementation that serializes the session may wait
                    # for the first response; an unprotected one finishes here.
                    second.result(timeout=1)
                except FutureTimeout:
                    pass
            finally:
                release_first.set()
            first_response = first.result(timeout=5)
            second_response = second.result(timeout=5)
            assert first_response.status_code == 200, first_response.text
            assert second_response.status_code == 200, second_response.text
        assert db.get_session_facts(sid) == {"industry": "manufacturing", "goal": "reduce_energy_costs"}
        assert db.get_session_facts(other_sid) == {}
