import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request
from flask_cors import CORS
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/chat.db")


def ensure_sqlite_directory(database_url: str):
    if not database_url.startswith("sqlite:///"):
        return

    database_path = database_url.removeprefix("sqlite:///")
    if not database_path or database_path == ":memory:":
        return

    database_dir = os.path.dirname(database_path)
    if database_dir:
        os.makedirs(database_dir, exist_ok=True)


ensure_sqlite_directory(DATABASE_URL)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class MessageNode(Base):
    __tablename__ = "message_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("message_nodes.id"),
        nullable=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


Base.metadata.create_all(bind=engine)


PROVIDER_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitAIChat/0.1",
}


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


def normalize_parent_id(value: Any):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("parent_id must be a positive integer or null.")
    if isinstance(value, int):
        if value > 0:
            return value
        raise ValueError("parent_id must be a positive integer or null.")
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() and int(stripped) > 0:
            return int(stripped)
    raise ValueError("parent_id must be a positive integer or null.")


def normalize_system_prompt(value: Any):
    if value is None:
        return []
    if not isinstance(value, str):
        raise ValueError("system_prompt must be a string.")

    content = value.strip()
    return [{"role": "system", "content": content}] if content else []


def node_to_dict(node: MessageNode):
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "role": node.role,
        "content": node.content,
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def rebuild_context_nodes(db, node_id: int | None):
    if node_id is None:
        return []

    nodes = []
    seen_ids = set()
    current_id = node_id

    while current_id is not None:
        if current_id in seen_ids:
            raise RuntimeError("Message node cycle detected.")
        seen_ids.add(current_id)

        node = db.get(MessageNode, current_id)
        if node is None:
            raise ValueError(f"Message node {current_id} does not exist.")

        nodes.append(node)
        current_id = node.parent_id

    return list(reversed(nodes))


def nodes_to_messages(nodes: list[MessageNode]):
    return [{"role": node.role, "content": node.content} for node in nodes]


def ensure_parent_exists(db, parent_id: int | None):
    if parent_id is not None and db.get(MessageNode, parent_id) is None:
        raise ValueError(f"Message node {parent_id} does not exist.")


def store_exchange(parent_id: int | None, user_content: str, assistant_content: str):
    with SessionLocal() as db:
        with db.begin():
            ensure_parent_exists(db, parent_id)

            user_node = MessageNode(
                parent_id=parent_id,
                role="user",
                content=user_content,
            )
            db.add(user_node)
            db.flush()

            assistant_node = MessageNode(
                parent_id=user_node.id,
                role="assistant",
                content=assistant_content,
            )
            db.add(assistant_node)
            db.flush()

            return node_to_dict(user_node), node_to_dict(assistant_node)


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
        headers={**PROVIDER_HEADERS, "Content-Type": "application/json", **(headers or {})},
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


@app.get("/api/ollama/models")
def ollama_models():
    try:
        base_url = normalize_ollama_base_url(request.args.get("base_url"))
        data = get_json(f"{base_url}/api/tags")
    except RuntimeError as exc:
        return response_fail(str(exc), 502)

    models = []
    for item in data.get("models", []):
        name = item.get("name") or item.get("model")
        if isinstance(name, str) and name.strip():
            models.append(name.strip())

    return response_ok({"models": sorted(set(models))})


@app.get("/api/context/<int:node_id>")
def context(node_id: int):
    try:
        with SessionLocal() as db:
            context_nodes = rebuild_context_nodes(db, node_id)
            node_payload = [node_to_dict(node) for node in context_nodes]
    except ValueError as exc:
        return response_fail(str(exc), 404)
    except RuntimeError as exc:
        return response_fail(str(exc), 500)

    return response_ok(
        {
            "node_id": node_id,
            "nodes": node_payload,
            "messages": [
                {"role": node["role"], "content": node["content"]}
                for node in node_payload
            ],
        }
    )


def nodes_payload():
    with SessionLocal() as db:
        nodes = list(db.scalars(select(MessageNode).order_by(MessageNode.id)))

    children_by_parent: dict[int | None, list[int]] = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node.id)

    payload = []
    for node in nodes:
        item = node_to_dict(node)
        item["children"] = children_by_parent.get(node.id, [])
        payload.append(item)

    return {
        "nodes": payload,
        "roots": children_by_parent.get(None, []),
    }


@app.get("/api/nodes")
def nodes():
    return response_ok(nodes_payload())


@app.get("/api/tree")
def tree():
    return response_ok(nodes_payload())


@app.get("/api/nodes/<int:node_id>/children")
def node_children(node_id: int):
    with SessionLocal() as db:
        if db.get(MessageNode, node_id) is None:
            return response_fail(f"Message node {node_id} does not exist.", 404)

        children = list(
            db.scalars(
                select(MessageNode)
                .where(MessageNode.parent_id == node_id)
                .order_by(MessageNode.id)
            )
        )

    return response_ok(
        {
            "node_id": node_id,
            "children": [node_to_dict(node) for node in children],
        }
    )


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    provider = payload.get("provider")
    model = payload.get("model")
    raw_messages = payload.get("messages")
    raw_message = payload.get("message")
    ollama_base_url = payload.get("ollama_base_url")

    if provider not in {"ollama", "gemini"}:
        return response_fail("Unsupported provider.")
    if not isinstance(model, str) or not model.strip():
        return response_fail("Model is required.")

    try:
        parent_id = normalize_parent_id(payload.get("parent_id"))
    except ValueError as exc:
        return response_fail(str(exc))

    try:
        if isinstance(raw_message, str):
            user_content = raw_message.strip()
            if not user_content:
                return response_fail("Message is required.")

            system_messages = normalize_system_prompt(payload.get("system_prompt"))
            with SessionLocal() as db:
                context_nodes = rebuild_context_nodes(db, parent_id)
                messages = [
                    *system_messages,
                    *nodes_to_messages(context_nodes),
                    {"role": "user", "content": user_content},
                ]
            messages = normalize_messages(messages)
            reply = provider_reply(provider, model.strip(), messages, ollama_base_url)
        else:
            if not isinstance(raw_messages, list) or len(raw_messages) == 0:
                return response_fail("Either message or messages is required.")

            with SessionLocal() as db:
                ensure_parent_exists(db, parent_id)
            messages = normalize_messages(raw_messages)
            user_message = next(
                (message for message in reversed(messages) if message["role"] == "user"),
                None,
            )
            user_content = user_message["content"] if user_message else ""
            reply = provider_reply(provider, model.strip(), messages, ollama_base_url)
    except ValueError as exc:
        return response_fail(str(exc))
    except RuntimeError as exc:
        return response_fail(str(exc), 502)

    if not reply:
        return response_fail("Provider returned an empty reply.", 502)

    try:
        user_node = None
        assistant_node = None
        if user_content:
            user_node, assistant_node = store_exchange(parent_id, user_content, reply)
    except ValueError as exc:
        return response_fail(str(exc), 404)

    return response_ok(
        {
            "role": "assistant",
            "content": reply,
            "user": user_node,
            "assistant": assistant_node,
            "node": assistant_node,
            "current_node_id": assistant_node["id"] if assistant_node else None,
            "currentNodeId": assistant_node["id"] if assistant_node else None,
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
