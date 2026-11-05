from __future__ import annotations

from .guards import DESCRIPTION_MAX, DESCRIPTION_MIN, TITLE_MAX
from .models import ProductCard

STATUS_TEXT = {
    "ok": "Готово к вычитке",
    "needs_review": "Требует внимания — см. раздел «Предупреждения»",
}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(card: ProductCard) -> str:
    lines: list[str] = [
        f"# {card.product_name}",
        "",
        f"**Статус:** {STATUS_TEXT[card.status]}  ",
        f"**Категория:** {card.category}",
        "",
        f"## SEO-заголовок ({card.seo_title_length}/{TITLE_MAX})",
        "",
        card.seo_title,
        "",
        f"## SEO-описание ({card.seo_description_length} симв., норма {DESCRIPTION_MIN}–{DESCRIPTION_MAX})",
        "",
        card.seo_description,
        "",
        "## Характеристики",
        "",
        "| Параметр | Значение |",
        "|---|---|",
    ]
    has_from_description = False
    for c in card.characteristics:
        value = f"*{c.value}*" if c.source == "missing" else _cell(c.value)
        if c.source == "description":
            value += " ¹"
            has_from_description = True
        lines.append(f"| {_cell(c.name)} | {value} |")
    if has_from_description:
        lines += ["", "¹ Значение взято из текстового описания, цитата сверена автоматически."]

    lines += ["", "## Поисковые запросы", ""]
    lines += [f"- {q}" for q in card.search_queries]

    lines += ["", "## Для менеджера", "", "**Кому подходит:**", ""]
    lines += [f"- {t}" for t in card.commercial.target_audience]
    lines += ["", "**Какие задачи решает:**", ""]
    lines += [f"- {t}" for t in card.commercial.tasks]
    lines += ["", "**Аргументы для клиента:**", ""]
    lines += [f"- {t}" for t in card.commercial.selling_points]

    if card.missing_fields or card.clarification_questions:
        lines += ["", "## Требует уточнения", ""]
        if card.missing_fields:
            lines.append("**Нет данных:** " + ", ".join(card.missing_fields) + ".")
        if card.clarification_questions:
            if card.missing_fields:
                lines.append("")
            lines.append("**Вопросы поставщику:**")
            lines.append("")
            lines += [f"- {q}" for q in card.clarification_questions]

    if card.warnings:
        lines += ["", "## Предупреждения", ""]
        lines += [f"- {w}" for w in card.warnings]

    m = card.meta
    lines += [
        "",
        "---",
        f"*Черновик сгенерирован автоматически: {m.model}, попыток: {m.attempts}, {m.generated_at}.*",
        "",
    ]
    return "\n".join(lines)
