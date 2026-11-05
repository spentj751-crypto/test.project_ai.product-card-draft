from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .categories import Category, detect_category, find_missing
from .guards import (
    DESCRIPTION_MAX,
    TITLE_MAX,
    Issue,
    check_draft,
    shorten_description,
    shorten_title,
    verify_extracted,
)
from .input_parser import ParsedInput, parse_input
from .llm import LLMClient, LLMError, Message
from .models import NO_DATA, CardMeta, Characteristic, LLMDraft, ProductCard
from .prompts import SYSTEM_PROMPT, build_format_repair_prompt, build_repair_prompt, build_user_prompt

log = logging.getLogger(__name__)


@dataclass
class Prepared:
    parsed: ParsedInput
    category: Category
    missing_expected: list[str]
    messages: list[Message]


def prepare(raw: str | bytes | dict[str, Any]) -> Prepared:
    """Всё, что делается без LLM. Бросает InputError при негодных данных."""
    parsed = parse_input(raw)
    product = parsed.product
    category = detect_category(product.name)
    missing = find_missing(category, list(product.specs))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(product, category, missing)},
    ]
    return Prepared(parsed=parsed, category=category, missing_expected=missing, messages=messages)


class DraftParseError(ValueError):
    pass


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_draft(content: str) -> LLMDraft:
    text = _FENCE_RE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise DraftParseError("в ответе нет JSON-объекта")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise DraftParseError(f"невалидный JSON ({exc.msg}, позиция {exc.pos})") from exc
    try:
        draft = LLMDraft.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
        )
        raise DraftParseError(f"структура не совпадает со схемой ({problems})") from exc
    return _clean_draft(draft)


def _clean_list(items: list[str]) -> list[str]:
    result, seen = [], set()
    for item in items:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            result.append(item)
    return result


def _clean_draft(draft: LLMDraft) -> LLMDraft:
    draft.seo_title = draft.seo_title.strip().rstrip(".")
    draft.seo_description = re.sub(r"\n{3,}", "\n\n", draft.seo_description.strip())
    draft.search_queries = _clean_list(draft.search_queries)
    draft.commercial.target_audience = _clean_list(draft.commercial.target_audience)
    draft.commercial.tasks = _clean_list(draft.commercial.tasks)
    draft.commercial.selling_points = _clean_list(draft.commercial.selling_points)
    draft.clarification_questions = _clean_list(draft.clarification_questions)
    return draft


def _errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def _run_llm(prepared: Prepared, llm: LLMClient, max_fix_attempts: int) -> tuple[LLMDraft, list[Issue], int]:
    """Генерация с циклом исправлений. Возвращает лучший черновик, его замечания и число вызовов."""
    product = prepared.parsed.product
    messages = list(prepared.messages)
    best: tuple[LLMDraft, list[Issue]] | None = None
    last_format_error = ""
    previous_content: str | None = None
    attempts = 0

    for attempt in range(max_fix_attempts + 1):
        attempts += 1
        content = llm.complete(messages)
        if previous_content is not None and content.strip() == previous_content:
            # Модель проигнорировала просьбу и повторила ответ слово в слово —
            # дальнейшие попытки только тратят токены.
            log.info("Попытка %d: модель повторила предыдущий ответ без изменений, повторы прекращены", attempts)
            break
        previous_content = content.strip()
        try:
            draft = parse_draft(content)
        except DraftParseError as exc:
            last_format_error = str(exc)
            log.warning("Попытка %d: %s", attempts, exc)
            messages += [
                {"role": "assistant", "content": content or "(пустой ответ)"},
                {"role": "user", "content": build_format_repair_prompt(str(exc))},
            ]
            continue

        issues = check_draft(draft, product)
        errors = _errors(issues)
        log.info(
            "Попытка %d: заголовок %d симв., описание %d симв.; ошибок %d, предупреждений %d",
            attempts, len(draft.seo_title), len(draft.seo_description),
            len(errors), len(issues) - len(errors),
        )
        for issue in errors:
            log.info("  ошибка — %s", issue)
        if best is None or len(errors) < len(_errors(best[1])):
            best = (draft, issues)
        if not errors:
            break
        if attempt < max_fix_attempts:
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": build_repair_prompt(issues)},
            ]

    if best is None:
        raise LLMError(f"Модель не вернула корректный JSON за {attempts} попыт(ки): {last_format_error}")
    return best[0], best[1], attempts


def _apply_safe_fixes(draft: LLMDraft, product, issues: list[Issue]) -> tuple[LLMDraft, list[Issue], list[str]]:
    """Последний рубеж для длины: только удаление текста, ничего не дописывается.

    Срабатывает, если модель не уложилась в лимиты за все попытки."""
    notes: list[str] = []
    error_fields = {i.field for i in _errors(issues)}

    if "seo_description" in error_fields and len(draft.seo_description) > DESCRIPTION_MAX:
        short = shorten_description(draft.seo_description)
        if short:
            notes.append(
                f"SEO-описание сокращено автоматически: {len(draft.seo_description)} → {len(short)} символов "
                "(удалены последние предложения самых длинных абзацев). Проверьте, что важное не потерялось."
            )
            draft = draft.model_copy(update={"seo_description": short})

    if "seo_title" in error_fields and len(draft.seo_title) > TITLE_MAX:
        short = shorten_title(draft.seo_title)
        if short:
            notes.append(f"SEO-заголовок сокращён автоматически: «{draft.seo_title}» → «{short}».")
            draft = draft.model_copy(update={"seo_title": short})

    if notes:
        issues = check_draft(draft, product)
        for note in notes:
            log.info("Автоисправление: %s", note)
    return draft, issues, notes


def build_characteristics(prepared: Prepared, draft: LLMDraft) -> tuple[list[Characteristic], list[str], list[str]]:
    """Собирает таблицу характеристик кодом. Возвращает (характеристики, недостающие поля, отброшенное)."""
    parsed = prepared.parsed
    product = parsed.product
    chars: list[Characteristic] = [
        Characteristic(name="Производитель", value=product.manufacturer, source="input")
        if product.manufacturer
        else Characteristic(name="Производитель", value=NO_DATA, source="missing")
    ]
    chars += [Characteristic(name=k, value=v, source="specs") for k, v in product.specs.items()]
    chars += [Characteristic(name=k, value=NO_DATA, source="missing") for k in parsed.empty_spec_keys]

    accepted, rejected = verify_extracted(draft.extracted_from_description, product)
    chars += [Characteristic(name=s.name, value=s.value, source="description", quote=s.quote) for s in accepted]

    available = list(product.specs) + [s.name for s in accepted]
    expected_missing = [
        title for title in find_missing(prepared.category, available)
        # не дублируем поле, если оно уже есть в specs, но пустое
        if not any(exp.title == title and any(exp.matches(k) for k in parsed.empty_spec_keys)
                   for exp in prepared.category.expected)
    ]
    chars += [Characteristic(name=title, value=NO_DATA, source="missing") for title in expected_missing]

    missing_fields = [c.name for c in chars if c.source == "missing"]
    return chars, missing_fields, rejected


def generate_card(raw: str | bytes | dict[str, Any], llm: LLMClient, max_fix_attempts: int = 2) -> ProductCard:
    started = time.monotonic()
    prepared = prepare(raw)
    product = prepared.parsed.product

    draft, issues, attempts = _run_llm(prepared, llm, max_fix_attempts)
    draft, issues, auto_fixes = _apply_safe_fixes(draft, product, issues)
    characteristics, missing_fields, rejected = build_characteristics(prepared, draft)

    errors = _errors(issues)
    warnings = list(prepared.parsed.notes)
    warnings += [f"Автоисправление: {n}" for n in auto_fixes]
    warnings += [f"Не исправлено автоматически — проверьте: {i}" for i in errors]
    warnings += [f"Стиль: {i}" for i in issues if i.severity == "warning"]
    warnings += [f"Характеристика из описания отброшена: {r}" for r in rejected]

    return ProductCard(
        status="needs_review" if errors else "ok",
        product_name=product.name,
        category=prepared.category.title,
        seo_title=draft.seo_title,
        seo_title_length=len(draft.seo_title),
        seo_description=draft.seo_description,
        seo_description_length=len(draft.seo_description),
        characteristics=characteristics,
        search_queries=draft.search_queries,
        commercial=draft.commercial,
        missing_fields=missing_fields,
        clarification_questions=draft.clarification_questions,
        warnings=warnings,
        meta=CardMeta(
            model=llm.model,
            attempts=attempts,
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            duration_sec=round(time.monotonic() - started, 2),
        ),
    )
