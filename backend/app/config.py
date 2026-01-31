import os
from dataclasses import dataclass
from typing import List

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str = _env("BACKEND_HOST", "0.0.0.0")
    port: int = _env_int("BACKEND_PORT", 8000)
    event_log_max: int = _env_int("EVENT_LOG_MAX", 1000)
    event_limit_default: int = _env_int("EVENT_LIMIT_DEFAULT", 200)
    summary_event_count: int = _env_int("SUMMARY_EVENT_COUNT", 20)

    ollama_url: str = _env("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = _env("OLLAMA_MODEL", "llama3.1:8b")

    allowed_origins: List[str] = [
        origin.strip()
        for origin in _env("ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


settings = Settings()
