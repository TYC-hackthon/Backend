from flask import Blueprint, request

from ..auth import AuthError, require_current_user
from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..services.message_nodes import (
    create_merge_node,
    ensure_parent_exists,
    nodes_to_messages,
    normalize_parent_id,
    normalize_system_prompt,
    rebuild_context_nodes,
    store_exchange,
)
from ..services.providers import normalize_messages, provider_reply


chat_bp = Blueprint("chat", __name__, url_prefix="/api")


@chat_bp.post("/chat")
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
        with SessionLocal() as db:
            user = require_current_user(db)
            user_id = user.id
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    try:
        if isinstance(raw_message, str):
            user_content = raw_message.strip()
            if not user_content:
                return response_fail("Message is required.")

            system_messages = normalize_system_prompt(payload.get("system_prompt"))
            with SessionLocal() as db:
                context_nodes = rebuild_context_nodes(db, parent_id, user_id)
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
                ensure_parent_exists(db, parent_id, user_id)
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
        exchange_node = None
        if user_content:
            user_node, assistant_node, exchange_node = store_exchange(
                parent_id,
                user_content,
                reply,
                user_id,
                ollama_base_url=ollama_base_url,
                metadata_model=model.strip() if model else None
            )
    except ValueError as exc:
        return response_fail(str(exc), 404)

    current_node_id = exchange_node["id"] if exchange_node else None
    return response_ok(
        {
            "role": "assistant",
            "content": reply,
            "user": user_node,
            "assistant": assistant_node,
            "exchange": exchange_node,
            "node": exchange_node,
            "current_node_id": current_node_id,
            "currentNodeId": current_node_id,
        }
    )


@chat_bp.post("/merge")
def merge():
    payload = request.get_json(silent=True) or {}

    try:
        node_a_id = normalize_parent_id(payload.get("node_a_id"))
        node_b_id = normalize_parent_id(payload.get("node_b_id"))
    except ValueError as exc:
        return response_fail(str(exc))

    if node_a_id is None or node_b_id is None:
        return response_fail("Both node_a_id and node_b_id are required.")

    if node_a_id == node_b_id:
        return response_fail("Cannot merge a branch with itself.")

    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            user_id = user.id
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    try:
        node = create_merge_node(node_a_id, node_b_id, user_id)
    except ValueError as exc:
        return response_fail(str(exc))

    current_node_id = node["id"]
    return response_ok(
        {
            "node": node,
            "current_node_id": current_node_id,
            "currentNodeId": current_node_id,
        }
    )
