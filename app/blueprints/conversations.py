from flask import Blueprint
from sqlalchemy import delete, select

from ..auth import AuthError, require_current_user
from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..models import BranchInfo, MessageNode
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
            user = require_current_user(db)
            context_nodes = rebuild_context_nodes(db, node_id, user.id)
            node_payload = [node_to_dict(node) for node in context_nodes]
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
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
    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            user_id = user.id
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok(nodes_payload(user_id))


@conversations_bp.delete("/nodes")
def clear_nodes():
    try:
        with SessionLocal() as db:
            with db.begin():
                user = require_current_user(db)
                db.execute(delete(BranchInfo).where(BranchInfo.user_id == user.id))
                result = db.execute(delete(MessageNode).where(MessageNode.user_id == user.id))
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok({"deleted": result.rowcount or 0})


@conversations_bp.get("/tree")
def tree():
    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            user_id = user.id
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok(nodes_payload(user_id))


@conversations_bp.get("/nodes/<int:node_id>/children")
def node_children(node_id: int):
    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            node = db.get(MessageNode, node_id)
            if node is None or node.user_id != user.id:
                return response_fail(f"Message node {node_id} does not exist.", 404)

            children = list(
                db.scalars(
                    select(MessageNode)
                    .where(MessageNode.parent_id == node_id)
                    .where(MessageNode.user_id == user.id)
                    .order_by(MessageNode.id)
                )
            )
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok(
        {
            "node_id": node_id,
            "children": [node_to_dict(node) for node in children],
        }
    )
