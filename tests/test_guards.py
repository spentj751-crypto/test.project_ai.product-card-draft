from app.guards import (
    check_draft,
    extract_numbers,
    find_unsupported_numbers,
    normalize_number,
    verify_extracted,
)
from app.input_parser import parse_input
from app.models import ExtractedSpec, LLMDraft

from .conftest import make_draft


def test_normalize_number():
    assert normalize_number("1,6") == "1.6"
    assert normalize_number("1.50") == "1.5"
    assert normalize_number("02") == "2"
    assert normalize_number("0,2") == "0.2"
    assert normalize_number("3.0") == "3"


def test_extract_numbers_handles_thousands_and_commas():
    nums = extract_numbers("Наработка 60 000 ч, диапазон 0–1,6 МПа, G1/2")
    assert {"60000", "0", "1.6", "1", "2"} <= nums


def test_invented_numbers_are_found():
    allowed = extract_numbers("0–1,6 МПа, класс точности 1,5")
    found = find_unsupported_numbers("Диапазон 0–1.6 МПа, корпус IP65, ГОСТ 2405-88", allowed)
    assert [n for n, _ in found] == ["65", "2405", "88"]


def test_clean_draft_passes(manometer):
    product = parse_input(manometer).product
    issues = check_draft(LLMDraft.model_validate(make_draft()), product)
    assert [i for i in issues if i.severity == "error"] == []


def test_hallucinated_facts_are_errors(manometer):
    product = parse_input(manometer).product
    draft = make_draft(seo_title="Манометр DM 02 IP65 с поверкой")
    issues = check_draft(LLMDraft.model_validate(draft), product)
    messages = " ".join(str(i) for i in issues)
    assert "«65»" in messages
    assert "поверка" in messages


def test_sensitive_term_allowed_when_in_input(manometer):
    manometer["specs"]["Межповерочный интервал"] = "2 года"
    product = parse_input(manometer).product
    draft = make_draft(seo_title="Манометр DM 02 с поверкой")
    issues = check_draft(LLMDraft.model_validate(draft), product)
    assert not [i for i in issues if "поверка" in str(i)]


def test_length_limits(manometer):
    product = parse_input(manometer).product
    draft = make_draft(seo_title="Манометр " * 10, seo_description="Короткий текст.", search_queries=["a", "b"])
    fields = {i.field for i in check_draft(LLMDraft.model_validate(draft), product) if i.severity == "error"}
    assert {"seo_title", "seo_description", "search_queries"} <= fields


def test_marketing_words_are_warnings(manometer):
    product = parse_input(manometer).product
    draft = make_draft(seo_title="Лучший манометр DM 02")
    issues = check_draft(LLMDraft.model_validate(draft), product)
    assert any(i.severity == "warning" and "лучший" in i.message for i in issues)
    assert not [i for i in issues if i.severity == "error"]


def test_verify_extracted_quotes(manometer):
    manometer["description"] = "Прибор предназначен для измерения избыточного давления. Межповерочный интервал — 2 года."
    product = parse_input(manometer).product
    accepted, rejected = verify_extracted([
        ExtractedSpec(name="Межповерочный интервал", value="2 года", quote="Межповерочный интервал - 2 года"),
        ExtractedSpec(name="Степень защиты", value="IP65", quote="Степень защиты IP65"),
        ExtractedSpec(name="Среда", value="вода", quote="измерения избыточного давления"),
        ExtractedSpec(name="класс точности", value="1,5", quote="избыточного давления"),
    ], product)
    assert [a.name for a in accepted] == ["Межповерочный интервал"]
    assert len(rejected) == 2  # IP65 — нет цитаты; «вода» — нет в цитате; класс точности уже в specs


def test_plc_unit_conversion_and_verification_are_caught():
    import json

    from .conftest import ROOT

    plc = json.loads((ROOT / "examples/input/plk210.json").read_text(encoding="utf-8"))
    product = parse_input(plc).product
    draft = make_draft(
        seo_title="ОВЕН ПЛК210 — процессор 1800 МГц",
        search_queries=["овен плк210", "плк210 с поверкой", "контроллер codesys 3.5"],
    )
    messages = " ".join(str(i) for i in check_draft(LLMDraft.model_validate(draft), product))
    assert "«1800»" in messages          # 1,8 ГГц нельзя пересчитывать в МГц
    assert "поверка" in messages         # у ПЛК210 во входе нет сведений о поверке
    assert "«3.5»" not in messages       # CODESYS 3.5 есть во входе


def _long_description() -> str:
    intro = ("Манометр показывающий DM 02 производства Манотомь предназначен для измерения избыточного давления. "
             "Прибор рассчитан на диапазон 0–1,6 МПа.")
    specs = " ".join([
        "Класс точности прибора составляет 1,5, что достаточно для технологического контроля.",
        "Присоединение к процессу выполняется через резьбу G1/2.",
        "Диаметр корпуса равен 100 мм, шкала хорошо читается на расстоянии.",
        "Модель DM 02 выпускается компанией Манотомь.",
        "Диапазон 0–1,6 МПа подходит для типовых систем водоснабжения и отопления.",
        "Резьба G1/2 совместима со стандартной запорной арматурой.",
        "Корпус диаметром 100 мм удобно размещать на щитах и трубопроводах.",
        "Класс точности 1,5 указан производителем в характеристиках.",
        "Измерение избыточного давления в диапазоне 0–1,6 МПа выполняется по круговой шкале.",
        "Манометр DM 02 не требует питания и работает автономно.",
        "Присоединение G1/2 позволяет устанавливать прибор без переходников на большинство отводов.",
        "Корпус 100 мм обеспечивает читаемость показаний при обходе оборудования.",
        "Производитель Манотомь поставляет модель DM 02 для промышленного применения.",
        "Шкала прибора DM 02 проградуирована в мегапаскалях до 1,6 МПа.",
        "Класс точности 1,5 позволяет использовать прибор для контроля режимов работы оборудования.",
        "Резьбовое присоединение G1/2 расположено радиально, снизу корпуса.",
        "Габарит корпуса 100 мм оптимален для щитового и местного монтажа.",
    ])
    usage = ("Манометр DM 02 применяется службами эксплуатации для контроля давления. "
             "Его используют монтажные организации при пусконаладке.")
    return f"{intro}\n\n{specs}\n\n{usage}"


def test_length_issue_speaks_in_sentences():
    from app.guards import description_length_issue

    text = _long_description() + " Дополнительное предложение о приборе DM 02." * 10
    issue = description_length_issue(text)
    assert issue is not None and "Удали примерно" in issue.message and "предложени" in issue.message


def test_shorten_description_only_removes_sentences():
    from app.guards import DESCRIPTION_MAX, DESCRIPTION_MIN, shorten_description, split_sentences

    text = _long_description()
    assert len(text) > DESCRIPTION_MAX
    short = shorten_description(text)
    assert short is not None and DESCRIPTION_MIN <= len(short) <= DESCRIPTION_MAX
    original = {s for p in text.split("\n\n") for s in split_sentences(p)}
    kept = [s for p in short.split("\n\n") for s in split_sentences(p)]
    assert set(kept) <= original                       # ничего нового не появилось
    assert short.split("\n\n")[0].startswith("Манометр показывающий DM 02")
    assert len(short.split("\n\n")) == 3               # абзацы сохранены


def test_shorten_title():
    from app.guards import shorten_title

    title = "Программируемый логический контроллер ОВЕН ПЛК210, CODESYS 3.5, 4 порта Ethernet"
    assert shorten_title(title) == "Программируемый логический контроллер ОВЕН ПЛК210, CODESYS 3.5"
    assert shorten_title("А" * 80) is None
