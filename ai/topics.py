"""Conservative vocabulary for routing queries and document headings."""
from __future__ import annotations

import re

_TOPICS = (
    ("photo", r"фотограф|распозна|снимк|\bфото\b"),
    ("solar", r"солнеч|панел|крыш|кровл|скат|фасад|накопител|сетевая станц|гибридн|генерац"),
    ("losses", r"потер|хищен|воров"),
    ("wholesale", r"оптов|орэм"),
    ("billing", r"тариф|ценов\w* катег|сч[её]т.{0,25}(?:вырос|рост)|(?:вырос|рост).{0,25}сч[её]т|за что.*плат"),
    ("metering", r"\b(?:аскуэ|аиис\s*куэ|askue)\b|платформ|уч[её]т|кабинет|сч[её]тчик|показан|магазин|цех|симк|sim"),
)


def identify_topic(text: str) -> str | None:
    for name, pattern in _TOPICS:
        if re.search(pattern, text, re.I):
            return name
    return None
