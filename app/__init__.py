from flask import Flask
from flask_cors import CORS

from .blueprints.chat import chat_bp
from .blueprints.conversations import conversations_bp
from .blueprints.health import health_bp
from .blueprints.providers import providers_bp
from .database import init_database


def create_app():
    flask_app = Flask(__name__)
    CORS(flask_app, resources={r"/api/*": {"origins": "*"}})

    init_database()

    flask_app.register_blueprint(health_bp)
    flask_app.register_blueprint(providers_bp)
    flask_app.register_blueprint(conversations_bp)
    flask_app.register_blueprint(chat_bp)

    return flask_app
