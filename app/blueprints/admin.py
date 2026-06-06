from flask import Blueprint, request
from sqlalchemy import delete, func, select

from ..auth import (
    AuthError,
    hash_password,
    message_node_counts_by_user,
    normalize_username,
    require_admin_user,
    user_to_dict,
    validate_password,
)
from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..models import MessageNode, User


admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def bool_payload(value, field_name: str):
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


@admin_bp.get("/users")
def users():
    try:
        with SessionLocal() as db:
            require_admin_user(db)
            node_counts = message_node_counts_by_user(db)
            user_rows = list(db.scalars(select(User).order_by(User.id)))
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok(
        {
            "users": [
                user_to_dict(user, node_counts.get(user.id, 0))
                for user in user_rows
            ],
        }
    )


@admin_bp.post("/users")
def create_user():
    payload = request.get_json(silent=True) or {}

    try:
        username = normalize_username(payload.get("username"))
        password = validate_password(payload.get("password"))
        is_admin = bool_payload(payload.get("is_admin", False), "is_admin")
    except ValueError as exc:
        return response_fail(str(exc))

    try:
        with SessionLocal() as db:
            with db.begin():
                require_admin_user(db)
                existing_user = db.scalar(select(User).where(User.username == username))
                if existing_user is not None:
                    return response_fail("Username already exists.", 409)

                user = User(
                    username=username,
                    password_hash=hash_password(password),
                    is_admin=is_admin,
                    is_active=True,
                )
                db.add(user)
                db.flush()
                payload = user_to_dict(user, 0)
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok({"user": payload})


@admin_bp.patch("/users/<int:user_id>")
def update_user(user_id: int):
    payload = request.get_json(silent=True) or {}

    try:
        with SessionLocal() as db:
            with db.begin():
                current_user = require_admin_user(db)
                user = db.get(User, user_id)
                if user is None:
                    return response_fail(f"User {user_id} does not exist.", 404)

                if "password" in payload:
                    user.password_hash = hash_password(validate_password(payload.get("password")))

                if "is_admin" in payload:
                    is_admin = bool_payload(payload.get("is_admin"), "is_admin")
                    if user.id == current_user.id and not is_admin:
                        return response_fail("You cannot remove admin access from your own account.")
                    user.is_admin = is_admin

                if "is_active" in payload:
                    is_active = bool_payload(payload.get("is_active"), "is_active")
                    if user.id == current_user.id and not is_active:
                        return response_fail("You cannot disable your own account.")
                    user.is_active = is_active

                node_count = db.scalar(
                    select(func.count(MessageNode.id))
                    .where(MessageNode.user_id == user.id)
                )
                response_user = user_to_dict(user, node_count or 0)
    except ValueError as exc:
        return response_fail(str(exc))
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok({"user": response_user})


@admin_bp.delete("/users/<int:user_id>/nodes")
def delete_user_nodes(user_id: int):
    try:
        with SessionLocal() as db:
            with db.begin():
                require_admin_user(db)
                user = db.get(User, user_id)
                if user is None:
                    return response_fail(f"User {user_id} does not exist.", 404)

                result = db.execute(delete(MessageNode).where(MessageNode.user_id == user.id))
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)

    return response_ok({"deleted": result.rowcount or 0})
