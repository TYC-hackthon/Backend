from flask import Flask
from flask_cors import CORS

from .blueprints.admin import admin_bp
from .blueprints.auth import auth_bp
from .blueprints.chat import chat_bp
from .blueprints.conversations import conversations_bp
from .blueprints.health import health_bp
from .blueprints.providers import providers_bp
from .blueprints.branches import branches_bp
from .config import CORS_ORIGINS, SECRET_KEY, SESSION_COOKIE_NAME
from .database import init_database


def create_app():
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY=SECRET_KEY,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    CORS(
        flask_app,
        resources={r"/api/*": {"origins": CORS_ORIGINS}},
        supports_credentials=True,
    )

    init_database()

    flask_app.register_blueprint(health_bp)
    flask_app.register_blueprint(auth_bp)
    flask_app.register_blueprint(admin_bp)
    flask_app.register_blueprint(providers_bp)
    flask_app.register_blueprint(conversations_bp)
    flask_app.register_blueprint(chat_bp)
    flask_app.register_blueprint(branches_bp)

    return flask_app
