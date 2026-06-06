import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})


DEFAULT_MODELS = [
    {
        "provider": "ollama",
        "label": "Ollama",
        "models": ["llama3.1", "llama3", "mistral", "gemma2"],
        "configured": True,
        "hint": "Uses OLLAMA_BASE_URL, defaulting to http://localhost:11434.",
    },
    {
        "provider": "gemini",
        "label": "Gemini",
        "models": ["gemini-1.5-flash", "gemini-1.5-pro"],
        "configured": bool(os.getenv("GEMINI_API_KEY")),
        "hint": "Set GEMINI_API_KEY before starting the backend.",
    },
]


def response_ok(data: Any):
    return jsonify({"ok": True, "data": data})


def response_fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None):
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
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


def chat_with_ollama(model: str, messages: list[dict[str, str]]):
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    data = post_json(
        f"{base_url}/api/chat",
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
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY and restart the backend.")

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


@app.get("/api/health")
def health():
    return response_ok({"status": "ready"})


@app.get("/api/models")
def models():
    return response_ok(DEFAULT_MODELS)


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    provider = payload.get("provider")
    model = payload.get("model")
    raw_messages = payload.get("messages")

    if provider not in {"ollama", "gemini"}:
        return response_fail("Unsupported provider.")
    if not isinstance(model, str) or not model.strip():
        return response_fail("Model is required.")
    if not isinstance(raw_messages, list) or len(raw_messages) == 0:
        return response_fail("At least one message is required.")

    try:
        messages = normalize_messages(raw_messages)
        if provider == "ollama":
            reply = chat_with_ollama(model.strip(), messages)
        else:
            reply = chat_with_gemini(model.strip(), messages)
    except ValueError as exc:
        return response_fail(str(exc))
    except RuntimeError as exc:
        return response_fail(str(exc), 502)

    if not reply:
        return response_fail("Provider returned an empty reply.", 502)

    return response_ok({"role": "assistant", "content": reply})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
