"""Types shared by the AI components, independent of the HTTP API."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

Stage = Literal["discover", "qualify", "recommend", "handoff"]


class TurnResult(TypedDict):
    answer: str
    stage: Stage
    source_ids: list[str]
    route: str
    updated_facts: dict
    proposed_action: Literal["offer_lead"] | None
    debug: dict | None


@dataclass(frozen=True)
class Chunk:
    source_id: str
    chunk_id: str
    heading: str
    text: str


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    score: float
    lexical_score: float
    character_score: float


@dataclass(frozen=True)
class Evidence:
    source_id: str
    chunk_id: str
    text: str


@dataclass(frozen=True)
class Plan:
    query: str
    route: str
    reason: str
    contact_declined: bool = False
    risky: bool = False
    topic: str | None = None
