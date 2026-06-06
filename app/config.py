import os


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/chat.db")

PROVIDER_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "GitAIChat/0.1",
}


def get_default_models():
    return [
        {
            "provider": "ollama",
            "label": "Ollama",
            "models": ["llama3.1", "llama3", "mistral", "gemma2"],
            "configured": True,
            "hint": "Uses OLLAMA_BASE_URL, defaulting to http://localhost:11434.",
        },
        {
            "provider": "gemini",
            "label": "Gemini",
            "models": ["gemini-1.5-flash", "gemini-1.5-pro"],
            "configured": bool(os.getenv("GEMINI_API_KEY")),
            "hint": "Set GEMINI_API_KEY before starting the backend.",
        },
    ]
