import json

from app.categories import detect_category, find_missing

from .conftest import ROOT


def test_detect_category():
    assert detect_category("Манометр показывающий DM 02").code == "manometer"
    assert detect_category("Гигрометр психрометрический ВИТ-1").code == "hygrometer"
    assert detect_category("ОВЕН ПЛК210").code == "plc"
    assert detect_category("Расходомер ультразвуковой").code == "generic"


def test_hygrometer_ranges_are_not_confused():
    category = detect_category("Гигрометр")
    missing = find_missing(category, ["Температурный диапазон измерения влажности, °С"])
    assert "Диапазон измерения влажности" in missing
    assert "Диапазон измерения температуры" in missing


def test_example_products():
    vit = json.loads((ROOT / "examples/input/vit-1.json").read_text(encoding="utf-8"))
    missing = find_missing(detect_category(vit["name"]), list(vit["specs"]))
    assert missing == ["Погрешность измерения", "Межповерочный интервал"]

    plc = json.loads((ROOT / "examples/input/plk210.json").read_text(encoding="utf-8"))
    assert find_missing(detect_category(plc["name"]), list(plc["specs"])) == []
