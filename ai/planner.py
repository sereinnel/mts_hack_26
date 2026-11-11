"""Small deterministic router. No LLM agents are needed for this baseline."""
from __future__ import annotations

import re

from .schemas import Plan
from .topics import identify_topic

_DECLINE = re.compile(
    r"(?:не\s+(?:хочу|готов[а]?|буду|нужно|надо)|без).{0,45}"
    r"(?:телефон|контакт|звон|менеджер|заявк)|"
    r"(?:телефон|контакт|менеджер|заявк).{0,25}(?:не\s+(?:нуж|хочу|готов)|потом|позже)",
    re.I,
)
_REQUEST = re.compile(
    r"(?:хочу|нужен|нужна|позовите|пригласите|соедините|свяжите|передайте).{0,35}"
    r"(?:менеджер|специалист|обратн\w* звон)|"
    r"(?:оставить|оформить|подать).{0,15}заявк|перезвоните",
    re.I,
)
_TECHNICAL = re.compile(
    r"(?:настро\w*|прошив\w*|пароль|схем\w* подключ\w*|подключ\w* провод\w*)"
    r".{0,50}(?:сч[её]тчик|прибор|модем|контроллер)|"
    r"юридическ\w* (?:заключение|консультаци)", re.I,
)
_RISK = re.compile(r"\d|цен|стоим|тариф|гарант|окуп|эконом|срок|закон|персональн|хищен", re.I)


def make_plan(message: str, history: list[dict]) -> Plan:
    declined = bool(_DECLINE.search(message))
    if not declined and _REQUEST.search(message):
        return Plan(message, "handoff", "explicit_contact_request")
    if not declined:
        for item in reversed(history):
            if item["role"] != "user":
                continue
            if _DECLINE.search(item["content"]):
                declined = True
                break
            if _REQUEST.search(item["content"]):
                break
    if _TECHNICAL.search(message):
        return Plan(message, "scope", "specialist_required", declined, True)
    if re.fullmatch(r"[\s!.,]*(?:привет|здравствуйте|добрый (?:день|вечер)|начать)[\s!.,]*", message, re.I):
        return Plan(message, "simple", "greeting", declined)

    # User statements supply situation context. Assistant claims are never evidence.
    previous = [item["content"] for item in history if item["role"] == "user"][-3:]
    # A preceding question supplies the subject of short replies such as "fourth".
    # It never supplies facts and cannot become an answer without a KB passage.
    last_question = ""
    if history and history[-1]["role"] == "assistant":
        sentence = re.split(r"(?<=[.!?])\s+", history[-1]["content"].strip())[-1]
        if sentence.endswith("?") and len(sentence) <= 250:
            last_question = sentence
    topic = identify_topic(message)
    if topic:
        previous = [text for text in previous if identify_topic(text) in {topic, None}]
    else:
        topic = identify_topic(last_question) or next(
            (name for text in reversed(previous) if (name := identify_topic(text))), None,
        )
    if last_question and identify_topic(last_question) in {topic, None}:
        previous.append(last_question)
    context = " ".join(text[-500:] for text in previous)[-1000:]
    if not context and re.fullmatch(
        r"[\s!?.]*(?:да|нет|подробнее|расскажите подробнее|сколько стоит|а цена|сколько это стоит)[\s!?.]*",
        message, re.I,
    ):
        return Plan(message, "clarify", "missing_topic", declined)
    query = message if not context else f"{message} {message} {context}"
    return Plan(query, "rag", "retrieve", declined, bool(_RISK.search(message)), topic)
