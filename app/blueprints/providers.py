from flask import Blueprint, request

from ..config import get_default_models
from ..http import response_fail, response_ok
from ..services.providers import get_json, normalize_ollama_base_url


providers_bp = Blueprint("providers", __name__, url_prefix="/api")


@providers_bp.get("/models")
def models():
    return response_ok(get_default_models())


@providers_bp.get("/ollama/models")
def ollama_models():
    try:
        base_url = normalize_ollama_base_url(request.args.get("base_url"))
        data = get_json(f"{base_url}/api/tags")
    except RuntimeError as exc:
        return response_fail(str(exc), 502)

    models = []
    for item in data.get("models", []):
        name = item.get("name") or item.get("model")
        if isinstance(name, str) and name.strip():
            models.append(name.strip())

    return response_ok({"models": sorted(set(models))})
