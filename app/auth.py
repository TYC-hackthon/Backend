import re

from flask import session
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from .models import MessageNode, User


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


def normalize_username(value):
    if not isinstance(value, str):
        raise ValueError("Username is required.")

    username = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must be 3-32 characters using letters, numbers, dots, dashes, or underscores.")
    return username


def validate_password(value):
    if not isinstance(value, str) or len(value) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return value


def hash_password(password: str):
    return generate_password_hash(password)


def verify_password(user: User, password: str):
    return check_password_hash(user.password_hash, password)


def user_to_dict(user: User, node_count: int | None = None):
    payload = {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if node_count is not None:
        payload["node_count"] = node_count
    return payload


def set_session_user(user: User):
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def clear_session_user():
    session.clear()


def get_current_user(db):
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        return None
    return user


def require_current_user(db):
    user = get_current_user(db)
    if user is None:
        raise AuthError("Authentication required.", 401)
    return user


def require_admin_user(db):
    user = require_current_user(db)
    if not user.is_admin:
        raise AuthError("Admin access is required.", 403)
    return user


def users_exist(db):
    return db.scalar(select(func.count(User.id))) > 0


def message_node_counts_by_user(db):
    rows = db.execute(
        select(MessageNode.user_id, func.count(MessageNode.id))
        .group_by(MessageNode.user_id)
    )
    return {user_id: count for user_id, count in rows}
