from __future__ import annotations

import logging
from typing import Protocol

import openai
from openai import OpenAI

from .config import Settings

log = logging.getLogger(__name__)

Message = dict[str, str]


class LLMError(RuntimeError):
    """Ошибка обращения к модели с понятным пользователю текстом."""


class LLMClient(Protocol):
    model: str

    def complete(self, messages: list[Message]) -> str: ...


class OpenAICompatibleClient:
    def __init__(self, settings: Settings):
        settings.require_key()
        self.settings = settings
        self.model = settings.model
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )

    def complete(self, messages: list[Message]) -> str:
        kwargs = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": 4000,
        }
        if self.settings.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise LLMError("API отклонил ключ (401). Проверьте LLM_API_KEY в .env.") from exc
        except openai.PermissionDeniedError as exc:
            raise LLMError(f"Нет доступа к модели (403): {_detail(exc)}") from exc
        except openai.RateLimitError as exc:
            raise LLMError("Превышен лимит запросов (429) — повторы не помогли, попробуйте позже.") from exc
        except openai.APITimeoutError as exc:
            raise LLMError(f"Модель не ответила за {self.settings.timeout:.0f} с. Увеличьте LLM_TIMEOUT или повторите.") from exc
        except openai.APIConnectionError as exc:
            raise LLMError(f"Не удалось подключиться к {self.settings.base_url}: проверьте сеть и LLM_BASE_URL.") from exc
        except openai.NotFoundError as exc:
            raise LLMError(f"Модель или адрес не найдены (404). Проверьте LLM_MODEL={self.settings.model!r} и LLM_BASE_URL.") from exc
        except openai.APIStatusError as exc:
            if exc.status_code == 402:
                raise LLMError("Недостаточно средств на балансе API (402).") from exc
            raise LLMError(f"Ошибка API ({exc.status_code}): {_detail(exc)}") from exc
        except openai.APIError as exc:
            raise LLMError(f"Ошибка API: {exc}") from exc

        if not response.choices:
            raise LLMError("API вернул ответ без вариантов (choices пуст).")
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if response.usage:
            log.info("LLM: %s токенов на входе, %s на выходе", response.usage.prompt_tokens, response.usage.completion_tokens)
        if choice.finish_reason == "length":
            log.warning("Ответ модели обрезан по max_tokens")
        return content


def _detail(exc: openai.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(exc.message if hasattr(exc, "message") else exc)
