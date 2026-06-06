from flask import Blueprint
from sqlalchemy import delete, select

from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..models import MessageNode
from ..services.message_nodes import (
    node_to_dict,
    nodes_payload,
    nodes_to_context_messages,
    rebuild_context_nodes,
)


conversations_bp = Blueprint("conversations", __name__, url_prefix="/api")


@conversations_bp.get("/context/<int:node_id>")
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
            "messages": nodes_to_context_messages(context_nodes),
        }
    )


@conversations_bp.get("/nodes")
def nodes():
    return response_ok(nodes_payload())


@conversations_bp.delete("/nodes")
def clear_nodes():
    with SessionLocal() as db:
        with db.begin():
            result = db.execute(delete(MessageNode))

    return response_ok({"deleted": result.rowcount or 0})


@conversations_bp.get("/tree")
def tree():
    return response_ok(nodes_payload())


@conversations_bp.get("/nodes/<int:node_id>/children")
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
