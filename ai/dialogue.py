"""Normalize ordinary turns and the dialogue-in-one-string evaluation format."""
from __future__ import annotations

import re

_ROLE = re.compile(r"(?im)^(пользователь|ассистент|user|assistant)\s*:\s*")


def normalize_turn(message: str, history: list[dict]) -> tuple[str, list[dict]]:
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    if not message.strip():
        raise ValueError("message must not be empty")
    if not isinstance(history, list):
        raise TypeError("history must be a list")
    turns = []
    for item in history:
        if not isinstance(item, dict):
            raise TypeError("history items must be dictionaries")
        if item.get("role") not in {"user", "assistant"}:
            raise ValueError("history role must be user or assistant")
        if not isinstance(item.get("content"), str):
            raise TypeError("history content must be a string")
        turns.append({"role": item["role"], "content": item["content"]})

    matches = list(_ROLE.finditer(message))
    if len(matches) < 2 or message[:matches[0].start()].strip():
        return message.strip(), turns
    embedded = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(message)
        role = "user" if match[1].lower() in {"пользователь", "user"} else "assistant"
        content = message[match.end():end].strip()
        if not content:
            raise ValueError("embedded dialogue contains an empty turn")
        embedded.append({"role": role, "content": content})
    if embedded[-1]["role"] != "user":
        raise ValueError("embedded dialogue must end with a user turn")
    return embedded[-1]["content"], turns + embedded[:-1]
