import pytest

from app.input_parser import InputError, parse_input


def test_invalid_json_reports_position():
    with pytest.raises(InputError) as exc:
        parse_input('{"name": "Манометр", "specs": {"a": "1",}}')
    assert exc.value.message == "Некорректный JSON"
    assert "строка 1" in exc.value.details[0]


def test_empty_input():
    with pytest.raises(InputError, match="Пустой ввод"):
        parse_input("   ")


def test_top_level_must_be_object():
    with pytest.raises(InputError, match="Некорректная структура"):
        parse_input("[1, 2]")


def test_name_is_required(manometer):
    manometer["name"] = "  "
    with pytest.raises(InputError) as exc:
        parse_input(manometer)
    assert any("name" in d for d in exc.value.details)


def test_needs_specs_or_description():
    with pytest.raises(InputError, match="Недостаточно данных"):
        parse_input({"name": "Термометр", "specs": {}, "description": " "})


def test_description_only_is_enough():
    parsed = parse_input({"name": "Термометр", "description": "Биметаллический термометр."})
    assert parsed.product.specs == {}
    assert parsed.product.manufacturer is None


def test_messy_values_are_normalized():
    parsed = parse_input({
        "name": "  Манометр DM 02 ",
        "manufacturer": "",
        "price": 100,
        "specs": {
            "класс точности": 1.5,
            "присоединение": "",
            "диаметр": None,
            "Исполнение": {"корпус": "сталь"},
            "Шкалы": ["0–1 МПа", "", "0–1,6 МПа"],
            "Индикация": True,
        },
        "description": "Описание.",
    })
    p = parsed.product
    assert p.name == "Манометр DM 02"
    assert p.manufacturer is None
    assert p.specs["класс точности"] == "1.5"
    assert p.specs["Исполнение / корпус"] == "сталь"
    assert p.specs["Шкалы"] == "0–1 МПа; 0–1,6 МПа"
    assert p.specs["Индикация"] == "да"
    assert parsed.empty_spec_keys == ["присоединение", "диаметр"]
    assert any("price" in n for n in parsed.notes)


def test_specs_as_list_of_pairs():
    parsed = parse_input({"name": "X", "specs": [{"name": "Питание", "value": "24 В"}]})
    assert parsed.product.specs == {"Питание": "24 В"}


def test_specs_wrong_type():
    with pytest.raises(InputError) as exc:
        parse_input({"name": "X", "specs": "24 В"})
    assert any("specs" in d or "ожидался" in d for d in exc.value.details)
