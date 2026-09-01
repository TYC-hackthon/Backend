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
        "merge_parent_a_id": getattr(node, "merge_parent_a_id", None),
        "merge_parent_b_id": getattr(node, "merge_parent_b_id", None),
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
    emitted_ids = set()

    def collect(curr_id, path_ids):
        if curr_id is None:
            return []

        curr_chain = []
        chain_ids = set()
        curr = curr_id
        while curr is not None:
            if curr in path_ids or curr in chain_ids:
                raise RuntimeError("Message node cycle detected.")
            chain_ids.add(curr)

            node = db.get(MessageNode, curr)
            if node is None:
                raise ValueError(f"Message node {curr} does not exist.")
            ensure_node_owner(node, user_id)

            curr_chain.append(node)
            curr = node.parent_id

        curr_chain.reverse()

        res = []
        for index, node in enumerate(curr_chain):
            if node.role == "merge":
                # Only the nodes between the merge node and the entry point are on
                # the active path; anything else that shows up again is a shared
                # ancestor of the two branches, not a cycle.
                merge_path = path_ids | {item.id for item in curr_chain[index:]}
                if getattr(node, "merge_parent_a_id", None) is not None:
                    res.extend(collect(node.merge_parent_a_id, merge_path))
                if getattr(node, "merge_parent_b_id", None) is not None:
                    res.extend(collect(node.merge_parent_b_id, merge_path))
            if node.id not in emitted_ids:
                emitted_ids.add(node.id)
                res.append(node)
        return res

    return collect(node_id, frozenset())


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

    if node.role == "merge":
        user_msg = node.user_content or "I'm now bringing in context from a separate conversation session."
        asst_msg = node.assistant_content or "Understood. I now have context from both sessions and will incorporate information from both."
        return [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": asst_msg},
        ]

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


def store_exchange(parent_id: int | None, user_content: str, assistant_content: str, user_id: int, provider: str = "ollama", metadata_model: str | None = None, ollama_base_url: str | None = None):
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
            
    try:
        import threading
        from .branch_info import upsert_branch_info
        def _run_upsert():
            try:
                upsert_branch_info(node_payload["id"], user_id, provider, metadata_model, ollama_base_url)
            except Exception:
                pass
        threading.Thread(target=_run_upsert, daemon=True).start()
    except Exception:
        pass

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


def nodes_to_text(nodes: list[MessageNode]) -> str:
    lines = []
    for node in nodes:
        if node.role == "exchange":
            if node.user_content:
                lines.append(f"User: {node.user_content}")
            if node.assistant_content:
                lines.append(f"Assistant: {node.assistant_content}")
        elif node.role in ("user", "assistant") and node.content:
            lines.append(f"{node.role.capitalize()}: {node.content}")
        elif node.role == "merge" and node.assistant_content:
            lines.append(f"Synthesized Context: {node.assistant_content}")
    return "\n".join(lines)


def synthesize_branches(
    text_a: str,
    text_b: str,
    node_a_id: int,
    node_b_id: int,
    provider: str,
    model: str,
    ollama_base_url: str | None = None,
) -> str:
    from .providers import provider_reply

    prompt = (
        "You are synthesizing the key takeaways and context from two conversation branches in a Git-like tree structure into a unified summary.\n"
        "Analyze the following two branches of conversation and synthesize their key points, agreed conclusions, and combined context into a comprehensive summary.\n"
        "Format the response cleanly with:\n"
        "1. Key points from Branch A\n"
        "2. Key points from Branch B\n"
        "3. Combined synthesis and consensus\n"
        "Be concise and informative."
    )
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": f"=== Branch A (Node #{node_a_id}) ===\n{text_a}\n\n=== Branch B (Node #{node_b_id}) ===\n{text_b}",
        },
    ]
    try:
        reply = provider_reply(provider, model, messages, ollama_base_url)
        if isinstance(reply, dict):
            return reply.get("content", "").strip()
        return str(reply).strip()
    except Exception as exc:
        print(f"[DEBUG] Merge synthesis failed: {exc}")
        return ""


def find_ancestor_path(db, node_id: int, user_id: int | None = None) -> list[MessageNode]:
    path = []
    curr = node_id
    seen = set()
    while curr is not None:
        if curr in seen:
            raise RuntimeError("Message node cycle detected.")
        seen.add(curr)
        node = db.get(MessageNode, curr)
        if node is None:
            raise ValueError(f"Message node {curr} does not exist.")
        ensure_node_owner(node, user_id)
        path.append(node)
        curr = node.parent_id
    path.reverse()
    return path


def calculate_branch_diff(db, node_a_id: int, node_b_id: int, user_id: int | None = None) -> dict[str, Any]:
    path_a = find_ancestor_path(db, node_a_id, user_id)
    path_b = find_ancestor_path(db, node_b_id, user_id)

    lca_node = None
    min_len = min(len(path_a), len(path_b))
    divergence_index = 0
    for i in range(min_len):
        if path_a[i].id == path_b[i].id:
            lca_node = path_a[i]
            divergence_index = i + 1
        else:
            break

    diff_a = path_a[divergence_index:]
    diff_b = path_b[divergence_index:]

    return {
        "lca_node": node_to_dict(lca_node) if lca_node else None,
        "branch_a_nodes": [node_to_dict(n) for n in diff_a],
        "branch_b_nodes": [node_to_dict(n) for n in diff_b],
    }


def create_merge_node(
    node_a_id: int,
    node_b_id: int,
    user_id: int,
    provider: str = "ollama",
    model: str | None = None,
    ollama_base_url: str | None = None,
    strategy: str = "synthesize",
):
    with SessionLocal() as db:
        with db.begin():
            node_a = db.get(MessageNode, node_a_id)
            if node_a is None:
                raise ValueError(f"Message node {node_a_id} does not exist.")
            ensure_node_owner(node_a, user_id)

            node_b = db.get(MessageNode, node_b_id)
            if node_b is None:
                raise ValueError(f"Message node {node_b_id} does not exist.")
            ensure_node_owner(node_b, user_id)

            synthesis_summary = ""
            if strategy == "synthesize" and model:
                context_a = rebuild_context_nodes(db, node_a_id, user_id)
                context_b = rebuild_context_nodes(db, node_b_id, user_id)
                text_a = nodes_to_text(context_a)
                text_b = nodes_to_text(context_b)
                if text_a.strip() or text_b.strip():
                    synthesis_summary = synthesize_branches(
                        text_a, text_b, node_a_id, node_b_id, provider, model, ollama_base_url
                    )

            user_content = f"Merged Branch #{node_a_id} and Branch #{node_b_id}."
            assistant_content = synthesis_summary if synthesis_summary else (
                "Understood. I now have context from both sessions and will incorporate information from both."
            )
            content = synthesis_summary if synthesis_summary else f"Merged from Node #{node_a_id} and Node #{node_b_id}"

            merge_node = MessageNode(
                user_id=user_id,
                parent_id=None,
                merge_parent_a_id=node_a_id,
                merge_parent_b_id=node_b_id,
                role="merge",
                content=content,
                user_content=user_content,
                assistant_content=assistant_content,
            )
            db.add(merge_node)
            db.flush()

            result = node_to_dict(merge_node)

    try:
        import threading
        from .branch_info import upsert_branch_info
        def _run_upsert():
            try:
                upsert_branch_info(result["id"], user_id, provider, model, ollama_base_url)
            except Exception:
                pass
        threading.Thread(target=_run_upsert, daemon=True).start()
    except Exception:
        pass

    return result
