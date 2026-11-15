"""Conservative extraction of explicitly stated customer industry and goal.

Only first-person assertions are supported. No model, product documents,
assistant assertions, numeric inference or contact/consent extraction is used.
Unrecognized fields supplied by the caller are preserved unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import re

_OWNER = r"(?:у\s+нас|мы(?:\s*[-—:]?\s*это)?|наше\s+предприятие|наша\s+компания|наша\s+организация)\s*[-—:]?\s+"
_SIZE = r"(?:(?:небольшое|крупное|малое|среднее|собственное)\s+)?"
_INDUSTRIES = (
    ("manufacturing", _SIZE + r"(?:(?:производственн\w*|промышленн\w*)\s+(?:предприяти\w*|компани\w*|организаци\w*)|завод\b|производство\b)"),
    ("retail", r"(?:сеть\s+магазинов|розничная\s+сеть|сетевой\s+ретейл)\b"),
    ("grid_company", r"(?:электросетевая|сетевая)\s+(?:компания|организация)\b"),
)
_INTENT = r"(?:(?:мы\s+)?(?:хотим|хочу|планируем)|нам\s+(?:нужно|надо)|(?:наша|моя)\s+(?:цель|задача)\s*[-—:]?|нужно|надо)\s+"
_NEGATIVE_INTENT = r"(?:(?:мы\s+)?(?:больше\s+)?не\s+(?:хотим|хочу|планируем)|нам\s+(?:больше\s+)?не\s+(?:нужно|надо))\s+"
_GOALS = (
    ("reduce_energy_costs", r"(?:снизить|снижать|сократить|сокращать|уменьшить|уменьшать)\s+(?:наши\s+)?(?:расходы|затраты|платежи|счета)\s+(?:на|за)\s+(?:электричество|электроэнергию|свет)\b"),
    ("automate_metering", r"(?:автоматизировать|наладить)\s+(?:уч[её]т|сбор\s+показаний)\b"),
    ("find_losses", r"(?:найти|находить|выявить|выявлять|искать)\s+(?:(?:коммерческие|возможные)\s+)?(?:потери|хищения)\b"),
)
_UNCONFIRMED = re.compile(r"\b(?:если|допустим|предположим|представим|возможно|кажется|наверное)\b", re.I)
_REPORTED = re.compile(r"\b(?:клиент\w*|заказчик\w*|он|она)\s+(?:сказал\w*|говорит|написал\w*)\b", re.I)


def _clauses(text: str):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"«[^»]*»|\"[^\"]*\"|“[^”]*”", " ", text)
    text = re.sub(r"(?m)^\s*>.*$", " ", text)
    for match in re.finditer(r"[^.!?;\n]+[.!?;]?", text):
        sentence = match[0].strip()
        if sentence.endswith("?") or _UNCONFIRMED.search(sentence) or _REPORTED.search(sentence):
            continue
        for clause in sentence.rstrip(".!;").split(","):
            clause = re.sub(r"^(?:нет|поправка|уточнение|на самом деле)\s*[:,]?\s*", "", clause.strip(), flags=re.I)
            if clause:
                yield clause


def _changes(text: str) -> tuple[dict[str, str], set[tuple[str, str]]]:
    confirmed: dict[str, str] = {}
    denied: set[tuple[str, str]] = set()
    for clause in _clauses(text):
        for value, pattern in _INDUSTRIES:
            if re.match(_OWNER + pattern, clause, re.I):
                confirmed["industry"] = value
                denied.discard(("industry", value))
            elif re.match(_OWNER + r"не\s+" + pattern, clause, re.I):
                denied.add(("industry", value))
                if confirmed.get("industry") == value:
                    confirmed.pop("industry")
        for value, pattern in _GOALS:
            if re.match(_INTENT + pattern, clause, re.I):
                confirmed["goal"] = value
                denied.discard(("goal", value))
            elif re.match(_NEGATIVE_INTENT + pattern, clause, re.I):
                denied.add(("goal", value))
                if confirmed.get("goal") == value:
                    confirmed.pop("goal")
    return confirmed, denied


def update_facts(message: str, history: list[dict], session_facts: dict) -> dict:
    """Return a full independent snapshot; explicit current corrections win."""
    facts = deepcopy(session_facts)
    historical: dict[str, str] = {}
    for item in history:
        if item["role"] != "user":
            continue
        confirmed, denied = _changes(item["content"])
        for name, value in denied:
            if historical.get(name) == value:
                historical.pop(name)
        historical.update(confirmed)
    # Old dialogues with empty snapshots can be recovered from user statements.
    # History must never overwrite a newer snapshot supplied by the backend.
    for name, value in historical.items():
        facts.setdefault(name, value)
    confirmed, denied = _changes(message)
    for name, value in denied:
        if facts.get(name) == value:
            facts.pop(name)
    facts.update(confirmed)
    return facts
