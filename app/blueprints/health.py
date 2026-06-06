from flask import Blueprint

from ..http import response_ok


health_bp = Blueprint("health", __name__, url_prefix="/api")


@health_bp.get("/health")
def health():
    return response_ok({"status": "ready"})
