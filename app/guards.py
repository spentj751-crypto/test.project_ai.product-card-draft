from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from .models import ExtractedSpec, LLMDraft, ProductInput

TITLE_MAX = 70
DESCRIPTION_MIN = 800
DESCRIPTION_MAX = 1200
QUERIES_MIN = 3
QUERIES_MAX = 5

Severity = Literal["error", "warning"]


@dataclass
class Issue:
    field: str
    message: str
    severity: Severity = "error"

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d)[   ](?=\d{3}(?!\d))")


def normalize_number(raw: str) -> str:
    num = raw.replace(",", ".")
    if "." in num:
        int_part, frac = num.split(".", 1)
        frac = frac.rstrip("0")
        int_part = int_part.lstrip("0") or "0"
        return f"{int_part}.{frac}" if frac else int_part
    return num.lstrip("0") or "0"


def extract_numbers(text: str) -> set[str]:
    text = _THOUSANDS_RE.sub("", text)
    return {normalize_number(m.group()) for m in _NUM_RE.finditer(text)}


def find_unsupported_numbers(text: str, allowed: set[str]) -> list[tuple[str, str]]:
    """Возвращает [(число, фрагмент с контекстом)] для чисел, которых нет в allowed."""
    collapsed = _THOUSANDS_RE.sub("", text)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _NUM_RE.finditer(collapsed):
        num = normalize_number(m.group())
        if num in allowed or num in seen:
            continue
        seen.add(num)
        start, end = max(0, m.start() - 30), min(len(collapsed), m.end() + 30)
        found.append((m.group(), collapsed[start:end].replace("\n", " ").strip()))
    return found


SENSITIVE_TERMS: dict[str, tuple[str, ...]] = {
    "Госреестр СИ": ("госреестр", "реестр си", "реестре си"),
    "поверка": ("поверк", "поверен", "поверочн"),
    "ГОСТ": ("гост",),
    "сертификаты": ("сертифик",),
    "взрывозащита": ("взрыв",),
    "гарантия": ("гарант",),
    "материал: нержавеющая сталь": ("нержав",),
    "материал: латунь": ("латун",),
    "материал: бронза": ("бронз",),
    "материал: алюминий": ("алюмин",),
    "материал: поликарбонат": ("поликарбонат",),
    "агрессивные среды": ("агрессивн",),
}

MARKETING_PATTERNS: tuple[str, ...] = (
    r"\bлучш\w*",
    r"\bсам(?:ый|ая|ое|ые)\b",
    r"№\s?1\b",
    r"\bуникальн\w*",
    r"\bидеальн\w*",
    r"\bнепревзойд\w*",
    r"\bлидер\w*",
    r"\bнадежнейш\w*|\bнадёжнейш\w*",
)


def _norm_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def input_corpus(product: ProductInput) -> str:
    """Весь входной текст одной строкой — эталон для сверки."""
    parts = [product.name, product.manufacturer or "", product.description]
    for key, value in product.specs.items():
        parts.append(f"{key}: {value}")
    return "\n".join(parts)


DESCRIPTION_TARGET = 1000
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")


def split_sentences(paragraph: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(paragraph.strip()) if s]


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def description_length_issue(text: str) -> Issue | None:
    n = len(text)
    if DESCRIPTION_MIN <= n <= DESCRIPTION_MAX:
        return None
    sentences = [s for p in text.split("\n\n") for s in split_sentences(p)]
    words = len(text.split())
    avg = n / max(len(sentences), 1)
    now = f"сейчас {n} символов ({words} слов, {len(sentences)} предложений), нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}"
    if n > DESCRIPTION_MAX:
        k = max(1, math.ceil((n - DESCRIPTION_TARGET) / avg))
        return Issue("seo_description", (
            f"{now}. Удали примерно {_plural(k, 'предложение', 'предложения', 'предложений')} "
            "о второстепенных характеристиках, чтобы осталось около 140 слов. "
            "Полная таблица характеристик выводится на странице отдельно — в описании достаточно 4–6 ключевых."
        ))
    k = max(1, math.ceil((DESCRIPTION_TARGET - n) / max(avg, 60)))
    return Issue("seo_description", (
        f"{now}. Добавь примерно {_plural(k, 'предложение', 'предложения', 'предложений')}, "
        "используя только факты из входных данных."
    ))


def shorten_description(text: str) -> str | None:
    """Безопасное автосокращение: удаляет целые предложения, ничего не дописывая.

    Каждый раз убирает последнее предложение самого длинного абзаца;
    первое предложение каждого абзаца сохраняется. None — если уложиться не вышло."""
    paragraphs = [split_sentences(p) for p in text.split("\n\n") if p.strip()]

    def joined() -> str:
        return "\n\n".join(" ".join(p) for p in paragraphs)

    result = joined()
    while len(result) > DESCRIPTION_MAX:
        candidates = [i for i, p in enumerate(paragraphs) if len(p) > 1]
        if not candidates:
            return None
        longest = max(candidates, key=lambda i: len(" ".join(paragraphs[i])))
        paragraphs[longest].pop()
        result = joined()
    return result if len(result) >= DESCRIPTION_MIN else None


def shorten_title(title: str) -> str | None:
    """Отрезает хвостовые части заголовка по разделителям («, », « — », «(»)."""
    t = title.strip()
    while len(t) > TITLE_MAX:
        cut = max(t.rfind(","), t.rfind(" — "), t.rfind(" - "), t.rfind(" | "), t.rfind(" ("))
        if cut <= 0:
            return None
        t = t[:cut].rstrip(" ,—-|(")
    return t if len(t) >= 15 else None


def _draft_text_fields(draft: LLMDraft) -> list[tuple[str, str]]:
    fields = [("seo_title", draft.seo_title), ("seo_description", draft.seo_description)]
    fields += [(f"search_queries[{i}]", q) for i, q in enumerate(draft.search_queries)]
    c = draft.commercial
    fields += [(f"commercial.target_audience[{i}]", t) for i, t in enumerate(c.target_audience)]
    fields += [(f"commercial.tasks[{i}]", t) for i, t in enumerate(c.tasks)]
    fields += [(f"commercial.selling_points[{i}]", t) for i, t in enumerate(c.selling_points)]
    fields += [(f"clarification_questions[{i}]", t) for i, t in enumerate(draft.clarification_questions)]
    return fields


def check_draft(draft: LLMDraft, product: ProductInput) -> list[Issue]:
    issues: list[Issue] = []
    corpus = input_corpus(product)
    allowed_numbers = extract_numbers(corpus)
    corpus_norm = _norm_text(corpus)

    title_len = len(draft.seo_title.strip())
    if title_len == 0:
        issues.append(Issue("seo_title", "пустой заголовок"))
    elif title_len > TITLE_MAX:
        issues.append(Issue("seo_title", f"{title_len} символов, допустимо не более {TITLE_MAX}. Сократи."))

    length_issue = description_length_issue(draft.seo_description.strip())
    if length_issue:
        issues.append(length_issue)

    queries = [q.strip() for q in draft.search_queries if q.strip()]
    if not QUERIES_MIN <= len(queries) <= QUERIES_MAX:
        issues.append(Issue("search_queries", f"{len(queries)} запросов, нужно {QUERIES_MIN}–{QUERIES_MAX}"))
    if len({q.lower() for q in queries}) != len(queries):
        issues.append(Issue("search_queries", "есть повторяющиеся запросы"))

    c = draft.commercial
    for name, items in (("commercial.target_audience", c.target_audience),
                        ("commercial.tasks", c.tasks),
                        ("commercial.selling_points", c.selling_points)):
        if not [i for i in items if i.strip()]:
            issues.append(Issue(name, "пустой список"))

    for field_name, text in _draft_text_fields(draft):
        for raw, context in find_unsupported_numbers(text, allowed_numbers):
            issues.append(Issue(
                field_name,
                f"число «{raw}» отсутствует во входных данных (фрагмент: «…{context}…»). "
                "Убери это сведение или замени значением из данных.",
            ))
        text_norm = _norm_text(text)
        for label, stems in SENSITIVE_TERMS.items():
            if any(s in text_norm for s in stems) and not any(s in corpus_norm for s in stems):
                issues.append(Issue(
                    field_name,
                    f"тема «{label}» — во входных данных таких сведений нет. Убери.",
                ))
        for pattern in MARKETING_PATTERNS:
            m = re.search(pattern, text_norm)
            if m:
                issues.append(Issue(
                    field_name,
                    f"рекламный оборот «{m.group()}» — замени нейтральной формулировкой.",
                    severity="warning",
                ))

    if "данных нет" in _norm_text(draft.seo_description):
        issues.append(Issue("seo_description", "в SEO-тексте не должно быть пометок «данных нет»", severity="warning"))

    return issues


_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "«": '"', "»": '"', "“": '"', "”": '"', "…": "..."})


def _norm_for_quote(text: str) -> str:
    text = _norm_text(text).translate(_DASHES)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .;,:")


def verify_extracted(
    extracted: list[ExtractedSpec],
    product: ProductInput,
) -> tuple[list[ExtractedSpec], list[str]]:
    """Оставляет только характеристики с подтверждённой цитатой.

    Возвращает (принятые, сообщения об отброшенных)."""
    description = _norm_for_quote(product.description)
    existing = {_norm_for_quote(k) for k in product.specs}
    accepted: list[ExtractedSpec] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for spec in extracted:
        name = spec.name.strip()
        value = spec.value.strip()
        key = _norm_for_quote(name)
        if not name or not value or key in existing or key in seen:
            continue
        quote = _norm_for_quote(spec.quote)
        if not quote or quote not in description:
            rejected.append(f"«{name}: {value}» — цитата не найдена в описании, значение отброшено.")
            continue
        if _norm_for_quote(value) not in quote:
            rejected.append(f"«{name}: {value}» — значения нет в приведённой цитате, значение отброшено.")
            continue
        seen.add(key)
        accepted.append(ExtractedSpec(name=name, value=value, quote=spec.quote.strip()))
    return accepted, rejected
