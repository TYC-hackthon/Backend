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


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: int = 180):
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
        with urlopen(req, timeout=timeout) as res:
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
        else os.getenv("OLLAMA_BASE_URL", "https://sheep.ysh.xx.kg")
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


def get_gemini_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return []

    try:
        data = get_json(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        )
        models = []
        for item in data.get("models", []):
            if "generateContent" in item.get("supportedGenerationMethods", []):
                name = item.get("name", "")
                if name.startswith("models/"):
                    models.append(name.replace("models/", "", 1))
        return sorted(set(models))
    except Exception:
        return []


def chat_with_ollama(model: str, messages: list[dict[str, str]], base_url: str | None = None):
    selected_base_url = normalize_ollama_base_url(base_url)
    url = f"{selected_base_url}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            **PROVIDER_HEADERS,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    content_parts = []
    prompt_tokens = 0
    eval_tokens = 0

    try:
        with urlopen(req, timeout=300) as res:
            for line in res:
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                    msg = chunk.get("message", {})
                    if "content" in msg and msg["content"]:
                        content_parts.append(msg["content"])
                    if chunk.get("done"):
                        prompt_tokens = chunk.get("prompt_eval_count", 0)
                        eval_tokens = chunk.get("eval_count", 0)
                except Exception:
                    continue
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Provider is unreachable: {exc.reason}") from exc

    content = "".join(content_parts).strip()
    total_tokens = prompt_tokens + eval_tokens
    return {
        "content": content,
        "prompt_eval_count": prompt_tokens,
        "eval_count": eval_tokens,
        "total_tokens": total_tokens,
    }


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
