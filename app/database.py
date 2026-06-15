import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


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


def ensure_message_node_columns(message_node_model):
    existing_columns = {
        column["name"]
        for column in inspect(engine).get_columns(message_node_model.__tablename__)
    }
    statements = []
    if "user_id" not in existing_columns:
        statements.append("ALTER TABLE message_nodes ADD COLUMN user_id INTEGER")
    if "user_content" not in existing_columns:
        statements.append("ALTER TABLE message_nodes ADD COLUMN user_content TEXT")
    if "assistant_content" not in existing_columns:
        statements.append("ALTER TABLE message_nodes ADD COLUMN assistant_content TEXT")
    statements.append("CREATE INDEX IF NOT EXISTS ix_message_nodes_user_id ON message_nodes (user_id)")

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def init_database():
    from .auth import hash_password
    from .models import MessageNode, User

    Base.metadata.create_all(bind=engine)
    ensure_message_node_columns(MessageNode)

    with SessionLocal() as db:
        if db.query(User).count() == 0:
            default_user = User(
                username="admin",
                password_hash=hash_password("admin1234"),
                is_admin=True,
                is_active=True,
            )
            db.add(default_user)
            db.commit()
