import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..config import PROVIDER_HEADERS


def provider_reply(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    ollama_base_url: str | None = None,
):
    if provider == "ollama":
        return chat_with_ollama(model, messages, ollama_base_url)
    return chat_with_gemini(model, messages)


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None):
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            **PROVIDER_HEADERS,
            "Content-Type": "application/json",
            **(headers or {}),
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider is unreachable: {exc.reason}") from exc


def get_json(url: str):
    req = Request(url, headers=PROVIDER_HEADERS, method="GET")

    try:
        with urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider is unreachable: {exc.reason}") from exc


def normalize_ollama_base_url(base_url: str | None = None):
    selected_base_url = (
        base_url.strip()
        if isinstance(base_url, str) and base_url.strip()
        else os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    selected_base_url = selected_base_url.rstrip("/")

    if not selected_base_url.startswith(("http://", "https://")):
        raise RuntimeError("Ollama Base URL must start with http:// or https://.")

    return selected_base_url


def normalize_messages(messages: list[dict[str, str]]):
    normalized = []
    for message in messages:
        role = message.get("role")
        content = message.get("content", "").strip()
        if role not in {"system", "user", "assistant"}:
            raise ValueError("Each message must have role system, user, or assistant.")
        if content:
            normalized.append({"role": role, "content": content})
    return normalized


def chat_with_ollama(model: str, messages: list[dict[str, str]], base_url: str | None = None):
    selected_base_url = normalize_ollama_base_url(base_url)

    data = post_json(
        f"{selected_base_url}/api/chat",
        {
            "model": model,
            "messages": messages,
            "stream": False,
        },
    )
    return data.get("message", {}).get("content", "").strip()


def chat_with_gemini(model: str, messages: list[dict[str, str]]):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Gemini is not configured. Set GEMINI_API_KEY and restart the backend."
        )

    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        text = message["content"]
        if message["role"] == "system":
            text = f"System instruction: {text}"
        contents.append({"role": role, "parts": [{"text": text}]})

    data = post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        {"contents": contents},
    )
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates.")

    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(part.get("text", "") for part in parts).strip()
