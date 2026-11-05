from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import ProductInput

KNOWN_FIELDS = {"name", "manufacturer", "specs", "description"}
MAX_DESCRIPTION_CHARS = 20_000


class InputError(ValueError):
    """Входные данные нельзя обработать. details — список конкретных проблем."""

    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []

    def __str__(self) -> str:
        if not self.details:
            return self.message
        return self.message + ":\n" + "\n".join(f"  - {d}" for d in self.details)


@dataclass
class ParsedInput:
    product: ProductInput
    notes: list[str] = field(default_factory=list)       # предупреждения о входе
    empty_spec_keys: list[str] = field(default_factory=list)  # поля specs без значения


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _scalar_to_str(value: Any) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value).strip()


def _flatten_specs(raw: Any, notes: list[str], empty: list[str]) -> dict[str, str]:
    """Приводит specs к плоскому словарю «название → строка».

    Поддерживает dict и список вида [{"name": ..., "value": ...}],
    вложенные словари разворачивает в «Группа / параметр»,
    списки значений склеивает через «; ».
    """
    if raw is None:
        return {}
    if isinstance(raw, list):
        converted: dict[str, Any] = {}
        for i, item in enumerate(raw, 1):
            if not isinstance(item, dict) or "name" not in item:
                raise InputError(
                    "Некорректное поле specs",
                    [f"элемент №{i}: ожидался объект вида {{\"name\": ..., \"value\": ...}}"],
                )
            converted[str(item["name"])] = item.get("value")
        raw = converted
    if not isinstance(raw, dict):
        raise InputError(
            "Некорректное поле specs",
            [f"ожидался объект «параметр: значение», получено: {type(raw).__name__}"],
        )

    result: dict[str, str] = {}

    def walk(prefix: str, obj: dict[str, Any]) -> None:
        for key, value in obj.items():
            key = str(key).strip()
            if not key:
                notes.append("В specs есть параметр без названия — пропущен.")
                continue
            full_key = f"{prefix} / {key}" if prefix else key
            if isinstance(value, dict):
                walk(full_key, value)
            elif isinstance(value, list):
                parts = [_scalar_to_str(v) for v in value if not _is_blank(v)]
                if parts:
                    result[full_key] = "; ".join(parts)
                else:
                    empty.append(full_key)
            elif _is_blank(value):
                empty.append(full_key)
            else:
                result[full_key] = _scalar_to_str(value)

    walk("", raw)
    return result


def parse_input(raw: str | bytes | dict[str, Any]) -> ParsedInput:
    """Принимает JSON-строку или уже разобранный словарь."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError("Файл не в кодировке UTF-8", [str(exc)]) from exc

    if isinstance(raw, str):
        if not raw.strip():
            raise InputError("Пустой ввод", ["передайте JSON с данными о товаре"])
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InputError(
                "Некорректный JSON",
                [f"строка {exc.lineno}, столбец {exc.colno}: {exc.msg}"],
            ) from exc
    else:
        data = raw

    if not isinstance(data, dict):
        raise InputError(
            "Некорректная структура",
            [f"ожидался JSON-объект с полями name, manufacturer, specs, description; получено: {type(data).__name__}"],
        )

    notes: list[str] = []
    empty: list[str] = []
    errors: list[str] = []

    unknown = sorted(set(data) - KNOWN_FIELDS)
    if unknown:
        notes.append("Поля не используются и проигнорированы: " + ", ".join(unknown) + ".")

    # name — обязательное
    name_raw = data.get("name")
    if isinstance(name_raw, (dict, list)):
        errors.append("name должно быть строкой")
        name = ""
    else:
        name = "" if _is_blank(name_raw) else _scalar_to_str(name_raw)
        if not name:
            errors.append("не заполнено обязательное поле name (название товара)")

    # manufacturer — желательное
    manufacturer_raw = data.get("manufacturer")
    if isinstance(manufacturer_raw, (dict, list)):
        errors.append("manufacturer должно быть строкой")
        manufacturer = None
    else:
        manufacturer = None if _is_blank(manufacturer_raw) else _scalar_to_str(manufacturer_raw)

    # description
    description_raw = data.get("description")
    if isinstance(description_raw, (dict, list)):
        errors.append("description должно быть строкой")
        description = ""
    else:
        description = "" if _is_blank(description_raw) else _scalar_to_str(description_raw)
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS]
        notes.append(f"Описание обрезано до {MAX_DESCRIPTION_CHARS} символов.")

    # specs
    try:
        specs = _flatten_specs(data.get("specs"), notes, empty)
    except InputError as exc:
        errors.extend(exc.details)
        specs = {}

    if errors:
        raise InputError("Входные данные не прошли проверку", errors)

    if not specs and not description:
        raise InputError(
            "Недостаточно данных для карточки",
            ["нужна хотя бы одна заполненная характеристика в specs или текст в description"],
        )

    if empty:
        notes.append("Характеристики без значения: " + ", ".join(empty) + ".")

    product = ProductInput(name=name, manufacturer=manufacturer, specs=specs, description=description)
    return ParsedInput(product=product, notes=notes, empty_spec_keys=empty)
