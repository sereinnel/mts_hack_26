from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .ai_adapter import consult_ai

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="EnergyTool Backend", version="0.1.0", lifespan=lifespan)
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST"], allow_headers=["*"])


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)


class LeadRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=5, max_length=40)
    company: str = Field(min_length=2, max_length=200)
    consent_to_contact: bool


def require_admin(x_admin_token: Annotated[str | None, Header()] = None):
    secret = os.getenv("ADMIN_TOKEN", "")
    # Do not expose real contact information by default.
    if not secret:
        raise HTTPException(status_code=503, detail="Set ADMIN_TOKEN to access lead list")
    import hmac
    if x_admin_token is None or not hmac.compare_digest(x_admin_token, secret):
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/health")
def health():
    return {"status": "ok", "ai_mode": "configured" if os.getenv("AI_FUNCTION") else "mock"}


@app.post("/api/sessions", status_code=201)
def create_session():
    return db.create_session()


@app.get("/api/sessions")
def get_sessions():
    return db.list_sessions()


@app.get("/api/sessions/{session_id}/messages")
def get_messages(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return db.list_messages(session_id)


@app.post("/api/sessions/{session_id}/close")
def close_session(session_id: str):
    if not db.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    db.close_session(session_id)
    return {"closed": True}


@app.post("/api/chat")
async def chat(payload: ChatRequest):
    if not db.session_exists(payload.session_id, active_only=True):
        raise HTTPException(status_code=404, detail="Active session not found")
    history = [{"role": item["role"], "content": item["content"]} for item in db.list_messages(payload.session_id)]
    session_facts = db.get_session_facts(payload.session_id)
    # Persist user text even if the upstream AI service later fails.
    db.add_message(payload.session_id, "user", payload.message)
    started = time.perf_counter()
    try:
        result = await consult_ai(payload.message, history, session_facts=session_facts)
    except Exception:
        log.exception("AI call failed for session_id=%s", payload.session_id)
        raise HTTPException(status_code=502, detail="AI temporarily unavailable") from None
    latency_ms = round((time.perf_counter() - started) * 1000)
    db.save_session_facts(payload.session_id, result["updated_facts"], result.get("stage"))
    db.add_message(payload.session_id, "assistant", result["answer"], result["sources"], result["intent"])
    return {"session_id": payload.session_id, "answer": result["answer"], "sources": result["sources"], "intent": result["intent"], "latency_ms": latency_ms}


@app.post("/api/leads", status_code=201)
def post_lead(payload: LeadRequest):
    if not db.session_exists(payload.session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    if not payload.consent_to_contact:
        raise HTTPException(status_code=400, detail="Consent to contact is required")
    messages = db.list_messages(payload.session_id)
    recent_requests = [m["content"] for m in messages if m["role"] == "user"][-8:]
    # Human-readable factual digest, no invented information. Improve with AI summarizer later.
    summary = (
        f"Компания: {payload.company}\n"
        f"Контакт: {payload.full_name}; телефон: {payload.phone}\n"
        "Основные реплики клиента:\n" + "\n".join(f"- {text[:400]}" for text in recent_requests)
    )
    return db.create_lead(payload.session_id, payload.full_name, payload.phone, payload.company, summary)


@app.get("/api/leads", dependencies=[Depends(require_admin)])
def get_leads():
    return db.list_leads()
