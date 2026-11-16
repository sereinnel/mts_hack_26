"""Small synchronous client for the protocol in the organizers' sample.

No requests on import; no SDK dependency; error messages never contain keys,
request bodies, response bodies or the configured URL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import suppress
from http.client import HTTPException
import json
import math
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Sanitized transport/protocol failure."""


class LLMConfigurationError(ValueError):
    """An explicitly requested model mode is not configured."""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float = 25.0
    max_tokens: int = 1600
    temperature: float = 0.0

    @classmethod
    def from_env(cls) -> LLMConfig:
        def first(*names: str) -> str:
            return next((os.environ[name].strip() for name in names
                         if os.getenv(name, "").strip() and os.environ[name].strip() != name), "")

        base = first("LLM_BASE_URL", "BASE_URL", "OPENAI_BASE_URL").rstrip("/")
        key = first("LLM_API_KEY", "OPENAI_API_KEY")
        model = first("LLM_MODEL", "GEN_MODEL", "OPENAI_MODEL")
        if not base or not key or not model:
            raise LLMConfigurationError("Configure LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
        try:
            parsed = urlsplit(base)
            timeout = float(os.getenv("AI_LLM_TIMEOUT_SECONDS", "25"))
            max_tokens = int(first("MAX_TOKENS") or "1600")
            temperature = float(first("TEMPERATURE") or "0")
        except ValueError:
            raise LLMConfigurationError("Invalid model API configuration") from None
        if (parsed.scheme not in {"http", "https"} or not parsed.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise LLMConfigurationError("LLM_BASE_URL must be an HTTP(S) API root without credentials or query")
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise LLMConfigurationError("AI_LLM_TIMEOUT_SECONDS must be in (0, 120]")
        if not 1 <= max_tokens <= 8192:
            raise LLMConfigurationError("MAX_TOKENS must be in [1, 8192]")
        if not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise LLMConfigurationError("TEMPERATURE must be in [0, 2]")
        return cls(base, key, model, timeout, max_tokens, temperature)


class ChatClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def complete(self, messages: list[dict], max_tokens: int | None = None) -> str:
        budget = self.config.max_tokens if max_tokens is None else min(max_tokens, self.config.max_tokens)
        body = json.dumps({
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": budget,
            "messages": messages,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.config.base_url + "/chat/completions", data=body, method="POST",
            headers={"Authorization": "Bearer " + self.config.api_key, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read())
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise LLMError("empty_model_response")
            return content.strip()
        except HTTPError as exc:
            with suppress(OSError, HTTPException):
                exc.close()
            raise LLMError(f"api_http_{exc.code}") from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise LLMError("api_transport_error") from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("invalid_model_response") from None


def json_object(text: str) -> dict:
    """Accept bare JSON or a single JSON fence; reject prose around the result."""
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text.strip(), re.S)
    if fenced:
        text = fenced[1]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        raise LLMError("invalid_structured_response") from None
    if not isinstance(payload, dict):
        raise LLMError("invalid_structured_response")
    return payload
