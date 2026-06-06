from flask import Blueprint, request
from sqlalchemy import select, update

from ..auth import (
    clear_session_user,
    get_current_user,
    hash_password,
    normalize_username,
    set_session_user,
    user_to_dict,
    users_exist,
    validate_password,
    verify_password,
)
from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..models import MessageNode, User


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.get("/status")
def status():
    with SessionLocal() as db:
        user = get_current_user(db)
        needs_setup = not users_exist(db)

    return response_ok(
        {
            "authenticated": user is not None,
            "needs_setup": needs_setup,
            "user": user_to_dict(user) if user else None,
        }
    )


@auth_bp.post("/setup")
def setup():
    payload = request.get_json(silent=True) or {}

    try:
        username = normalize_username(payload.get("username"))
        password = validate_password(payload.get("password"))
    except ValueError as exc:
        return response_fail(str(exc))

    with SessionLocal() as db:
        with db.begin():
            if users_exist(db):
                return response_fail("Initial setup has already been completed.", 409)

            user = User(
                username=username,
                password_hash=hash_password(password),
                is_admin=True,
                is_active=True,
            )
            db.add(user)
            db.flush()
            db.execute(
                update(MessageNode)
                .where(MessageNode.user_id.is_(None))
                .values(user_id=user.id)
            )

        set_session_user(user)

    return response_ok(
        {
            "authenticated": True,
            "needs_setup": False,
            "user": user_to_dict(user),
        }
    )


@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}

    try:
        username = normalize_username(payload.get("username"))
    except ValueError:
        return response_fail("Invalid username or password.", 401)

    password = payload.get("password")
    if not isinstance(password, str):
        return response_fail("Invalid username or password.", 401)

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None or not user.is_active or not verify_password(user, password):
            return response_fail("Invalid username or password.", 401)

        set_session_user(user)

    return response_ok(
        {
            "authenticated": True,
            "needs_setup": False,
            "user": user_to_dict(user),
        }
    )


@auth_bp.post("/logout")
def logout():
    clear_session_user()
    return response_ok({"authenticated": False})
