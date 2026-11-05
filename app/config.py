"""Настройки из переменных окружения (.env подхватывается автоматически)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} должно быть числом, получено: {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, default))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout: float
    max_retries: int        # повторы при сетевых ошибках, 429 и 5xx (делает SDK, с backoff)
    json_mode: bool         # response_format=json_object; выключить, если провайдер не поддерживает
    max_fix_attempts: int   # сколько раз просить модель исправить ответ после проверки

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("LLM_API_KEY", "").strip(),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("LLM_MODEL", "deepseek-chat").strip(),
            temperature=_env_float("LLM_TEMPERATURE", 0.2),
            timeout=_env_float("LLM_TIMEOUT", 90),
            max_retries=_env_int("LLM_MAX_RETRIES", 3),
            json_mode=_env_bool("LLM_JSON_MODE", True),
            max_fix_attempts=_env_int("MAX_FIX_ATTEMPTS", 2),
        )

    def require_key(self) -> None:
        if not self.api_key:
            raise ConfigError(
                "Не задан LLM_API_KEY. Скопируйте .env.example в .env и вставьте ключ "
                "(или задайте переменную окружения LLM_API_KEY)."
            )
