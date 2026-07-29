from typing import Any

from sqlalchemy import select

from ..database import SessionLocal
from ..models import MessageNode


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
    user_content = node.user_content
    assistant_content = node.assistant_content
    if node.role == "user" and user_content is None:
        user_content = node.content
    if node.role == "assistant" and assistant_content is None:
        assistant_content = node.content

    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "role": node.role,
        "content": node.content,
        "user_content": user_content,
        "assistant_content": assistant_content,
        "created_at": node.created_at.isoformat() if node.created_at else None,
    }


def ensure_node_owner(node: MessageNode, user_id: int | None):
    if user_id is not None and node.user_id != user_id:
        raise ValueError(f"Message node {node.id} does not exist.")


def rebuild_context_nodes(db, node_id: int | None, user_id: int | None = None):
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
        ensure_node_owner(node, user_id)

        nodes.append(node)
        current_id = node.parent_id

    return list(reversed(nodes))


def nodes_to_messages(nodes: list[MessageNode]):
    messages = []
    for node in nodes:
        messages.extend(node_to_messages(node))
    return messages


def node_to_messages(node: MessageNode):
    if node.role == "exchange":
        messages = []
        if node.user_content:
            messages.append({"role": "user", "content": node.user_content})
        if node.assistant_content:
            messages.append({"role": "assistant", "content": node.assistant_content})
        return messages

    if node.role in {"user", "assistant"} and node.content:
        return [{"role": node.role, "content": node.content}]

    return []


def nodes_to_context_messages(nodes: list[MessageNode]):
    messages = []
    for node in nodes:
        for message in node_to_messages(node):
            messages.append(
                {
                    **message,
                    "node_id": node.id,
                    "parent_id": node.parent_id,
                    "created_at": node.created_at.isoformat() if node.created_at else None,
                }
            )
    return messages


def ensure_parent_exists(db, parent_id: int | None, user_id: int | None = None):
    if parent_id is None:
        return

    node = db.get(MessageNode, parent_id)
    if node is None:
        raise ValueError(f"Message node {parent_id} does not exist.")
    ensure_node_owner(node, user_id)


def message_projection(node_payload: dict[str, Any], role: str, content: str):
    return {
        **node_payload,
        "role": role,
        "content": content,
    }


def store_exchange(parent_id: int | None, user_content: str, assistant_content: str, user_id: int):
    with SessionLocal() as db:
        with db.begin():
            ensure_parent_exists(db, parent_id, user_id)

            exchange_node = MessageNode(
                user_id=user_id,
                parent_id=parent_id,
                role="exchange",
                content=user_content,
                user_content=user_content,
                assistant_content=assistant_content,
            )
            db.add(exchange_node)
            db.flush()

            node_payload = node_to_dict(exchange_node)
            return (
                message_projection(node_payload, "user", user_content),
                message_projection(node_payload, "assistant", assistant_content),
                node_payload,
            )


def nodes_payload(user_id: int):
    with SessionLocal() as db:
        nodes = list(
            db.scalars(
                select(MessageNode)
                .where(MessageNode.user_id == user_id)
                .order_by(MessageNode.id)
            )
        )

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


def merge_branches(node_a_id: int | None, node_b_id: int | None, user_id: int):
    with SessionLocal() as db:
        with db.begin():
            chain_a = rebuild_context_nodes(db, node_a_id, user_id)
            chain_b = rebuild_context_nodes(db, node_b_id, user_id)

            all_copied_nodes = []

            last_parent_id = None
            for node in chain_a:
                new_node = MessageNode(
                    user_id=node.user_id,
                    role=node.role,
                    content=node.content,
                    user_content=node.user_content,
                    assistant_content=node.assistant_content,
                    parent_id=last_parent_id,
                )
                db.add(new_node)
                db.flush()
                all_copied_nodes.append(new_node)
                last_parent_id = new_node.id

            separator_node = MessageNode(
                user_id=user_id,
                parent_id=last_parent_id,
                role="exchange",
                content="I'm now bringing in context from a separate conversation session.",
                user_content="I'm now bringing in context from a separate conversation session.",
                assistant_content="Understood. I now have context from both sessions and will incorporate information from both.",
            )
            db.add(separator_node)
            db.flush()
            all_copied_nodes.append(separator_node)
            last_parent_id = separator_node.id

            for node in chain_b:
                new_node = MessageNode(
                    user_id=node.user_id,
                    role=node.role,
                    content=node.content,
                    user_content=node.user_content,
                    assistant_content=node.assistant_content,
                    parent_id=last_parent_id,
                )
                db.add(new_node)
                db.flush()
                all_copied_nodes.append(new_node)
                last_parent_id = new_node.id

            return (
                [node_to_dict(n) for n in all_copied_nodes],
                last_parent_id,
            )
