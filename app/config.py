import os


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/chat.db")
SECRET_KEY = os.getenv("SECRET_KEY", "git-ai-chat-dev-secret")
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "git_ai_chat_session")
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
CORS_ORIGINS = "*" if "*" in _cors_origins else _cors_origins

# Embedding configuration
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_MAX_TOKENS = int(os.getenv("EMBEDDING_MAX_TOKENS", "6000"))

# Metadata LLM configuration
METADATA_MODEL = os.getenv("METADATA_MODEL", "gemma3:4b")

PROVIDER_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitAIChat/0.1",
}


def get_default_models():
    return [
        {
            "provider": "ollama",
            "label": "Ollama",
            "models": ["gemma3:4b", "llama3.1", "mistral", "gemma2"],
            "configured": True,
            "hint": "Uses OLLAMA_BASE_URL, defaulting to https://sheep.ysh.xx.kg.",
        },
        {
            "provider": "gemini",
            "label": "Gemini",
            "models": ["gemini-1.5-flash", "gemini-1.5-pro"],
            "configured": bool(os.getenv("GEMINI_API_KEY")),
            "hint": "Set GEMINI_API_KEY before starting the backend.",
        },
    ]
