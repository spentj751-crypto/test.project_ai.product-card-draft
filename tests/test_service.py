import json

import pytest

from app.llm import LLMError
from app.models import NO_DATA
from app.render import to_markdown
from app.service import generate_card, parse_draft

from .conftest import ROOT, FakeLLM, make_draft


def test_happy_path(manometer):
    llm = FakeLLM(make_draft())
    card = generate_card(manometer, llm)
    assert card.status == "ok"
    assert card.meta.attempts == 1
    assert card.characteristics[0].name == "Производитель"
    values = {c.name: c.value for c in card.characteristics}
    assert values["класс точности"] == "1,5"
    assert values["Степень защиты (IP)"] == NO_DATA
    assert "Межповерочный интервал" in card.missing_fields


def test_hallucination_is_sent_back_and_fixed(manometer):
    bad = make_draft(seo_title="Манометр DM 02 IP65 Манотомь")
    llm = FakeLLM(bad, make_draft())
    card = generate_card(manometer, llm)
    assert card.status == "ok"
    assert card.meta.attempts == 2
    repair_request = llm.calls[1][-1]["content"]
    assert "«65»" in repair_request


def test_invalid_json_from_model_is_retried(manometer):
    llm = FakeLLM("Конечно! Вот карточка: {не json", "```json\n" + json.dumps(make_draft(), ensure_ascii=False) + "\n```")
    card = generate_card(manometer, llm)
    assert card.meta.attempts == 2
    assert "JSON" in llm.calls[1][-1]["content"]


def test_unfixable_draft_is_flagged(manometer):
    bad1 = make_draft(seo_description="Манометр с корпусом IP65. " * 40)
    bad2 = make_draft(seo_description="Манометр DM 02, корпус IP65. " * 36)
    bad3 = make_draft(seo_description="Корпус манометра DM 02 — IP65. " * 34)
    card = generate_card(manometer, FakeLLM(bad1, bad2, bad3), max_fix_attempts=2)
    assert card.status == "needs_review"
    assert card.meta.attempts == 3
    assert any("Не исправлено" in w and "65" in w for w in card.warnings)


def test_model_never_returns_json(manometer):
    with pytest.raises(LLMError, match="корректный JSON"):
        generate_card(manometer, FakeLLM("не json"), max_fix_attempts=1)


def test_input_error_does_not_call_llm():
    llm = FakeLLM(make_draft())
    with pytest.raises(Exception):
        generate_card('{"name": ""}', llm)
    assert llm.calls == []


def test_extraction_from_description_closes_missing_field():
    vit = json.loads((ROOT / "examples/input/vit-1.json").read_text(encoding="utf-8"))
    draft = make_draft(
        seo_title="Гигрометр психрометрический ВИТ-1 с поверкой",
        seo_description=("Гигрометр психрометрический ВИТ-1 измеряет влажность 20...90 % при температуре 0...25 °С. " * 12)[:1000],
        search_queries=["гигрометр вит-1", "гигрометр психрометрический", "вит-1 с поверкой"],
        commercial={"target_audience": ["офисы"], "tasks": ["контроль влажности"], "selling_points": ["цена деления 0,2 °С"]},
        extracted_from_description=[
            {"name": "Межповерочный интервал", "value": "2 года", "quote": "межповерочный интервал 2 года"},
            {"name": "Погрешность", "value": "±2 %", "quote": "погрешность ±2 %"},
        ],
    )
    card = generate_card(vit, FakeLLM(draft))
    by_name = {c.name: c for c in card.characteristics}
    assert by_name["Межповерочный интервал"].source == "description"
    assert by_name["Производитель"].value == NO_DATA
    assert "Межповерочный интервал" not in card.missing_fields
    assert "Погрешность измерения" in card.missing_fields
    assert any("отброшена" in w for w in card.warnings)


def test_empty_spec_is_not_duplicated():
    data = {"name": "Манометр DM 02", "specs": {"присоединение": "", "класс точности": "1,5"},
            "description": "Прибор предназначен для измерения избыточного давления."}
    draft = make_draft(
        seo_title="Манометр DM 02 класс точности 1,5",
        seo_description=("Манометр DM 02 для измерения избыточного давления, класс точности 1,5. " * 15)[:1000],
        search_queries=["манометр dm 02", "манометр класс точности 1,5", "манометр избыточного давления"],
        commercial={"target_audience": ["КИПиА"], "tasks": ["контроль давления"], "selling_points": ["класс точности 1,5"]},
    )
    card = generate_card(data, FakeLLM(draft))
    names = [c.name.lower() for c in card.characteristics]
    assert names.count("присоединение") == 1


def test_markdown_render(manometer):
    card = generate_card(manometer, FakeLLM(make_draft()))
    md = to_markdown(card)
    for heading in ("## SEO-заголовок", "## SEO-описание", "## Характеристики", "## Поисковые запросы",
                    "## Для менеджера", "## Требует уточнения"):
        assert heading in md
    assert "*данных нет*" in md


def test_parse_draft_strips_fences():
    draft = parse_draft("```json\n" + json.dumps(make_draft(), ensure_ascii=False) + "\n```")
    assert draft.seo_title.startswith("Манометр")


def test_too_long_description_is_shortened_safely(manometer):
    from .test_guards import _long_description

    long_draft = make_draft(seo_description=_long_description())
    llm = FakeLLM(long_draft)                         # модель упорно пишет слишком длинно
    card = generate_card(manometer, llm, max_fix_attempts=2)
    assert card.meta.attempts == 2   # второй ответ совпал с первым — дальше не спрашиваем
    assert "Удали примерно" in llm.calls[1][-1]["content"]
    assert card.status == "ok"
    assert 800 <= card.seo_description_length <= 1200
    assert any(w.startswith("Автоисправление") for w in card.warnings)
