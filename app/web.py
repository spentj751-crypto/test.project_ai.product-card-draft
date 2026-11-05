"""Веб-интерфейс: одна страница с формой + JSON API.

Запуск:  uvicorn app.web:app --reload   →   http://127.0.0.1:8000
Swagger: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from .config import PROJECT_ROOT, ConfigError, Settings
from .input_parser import InputError
from .llm import LLMError, OpenAICompatibleClient
from .render import to_markdown
from .service import generate_card, prepare

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="AI-помощник для карточек товаров КИПиА",
    description="Принимает JSON с данными о приборе и возвращает черновик карточки товара.",
    version="0.1.0",
)

STATIC_DIR = PROJECT_ROOT / "app" / "static"
EXAMPLE_DIRS = [PROJECT_ROOT / "examples" / "input", PROJECT_ROOT / "examples" / "edge_cases"]


def _error(status: int, message: str, details: list[str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message, "details": details or []})


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/examples", summary="Примеры входных данных")
def examples() -> list[dict]:
    result = []
    for directory in EXAMPLE_DIRS:
        for path in sorted(directory.glob("*.json")):
            result.append({
                "id": f"{directory.name}/{path.stem}",
                "group": "Товары" if directory.name == "input" else "Проблемные входы",
                "text": path.read_text(encoding="utf-8"),
            })
    return result


@app.post("/api/validate", summary="Проверить вход без вызова LLM")
async def validate(request: Request):
    body = await request.body()
    try:
        prepared = prepare(body)
    except InputError as exc:
        return _error(422, exc.message, exc.details)
    product = prepared.parsed.product
    return {
        "category": prepared.category.title,
        "specs_count": len(product.specs),
        "description_length": len(product.description),
        "manufacturer": product.manufacturer,
        "missing_expected": prepared.missing_expected,
        "notes": prepared.parsed.notes,
    }


@app.post(
    "/api/generate",
    summary="Сгенерировать карточку",
    description="Тело запроса — JSON-объект: name, manufacturer, specs, description.",
)
async def generate(request: Request):
    body = await request.body()
    try:
        prepare(body)  # быстрая проверка входа до создания клиента
        settings = Settings.from_env()
        llm = OpenAICompatibleClient(settings)
        card = await run_in_threadpool(generate_card, body, llm, settings.max_fix_attempts)
    except InputError as exc:
        return _error(422, exc.message, exc.details)
    except ConfigError as exc:
        return _error(500, str(exc))
    except LLMError as exc:
        return _error(502, str(exc))
    return {"card": json.loads(card.model_dump_json()), "markdown": to_markdown(card)}
