"""Шаблоны категорий: какие характеристики покупатель ожидает увидеть.

Категория определяется по ключевым словам в названии, без LLM, —
так список «чего не хватает» получается детерминированным и проверяемым.
Сопоставление с ключами specs — по основам слов: поле считается найденным,
если в названии параметра есть все основы хотя бы из одного варианта
и нет ни одной основы-исключения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExpectedField:
    title: str
    variants: tuple[tuple[str, ...], ...]
    exclude: tuple[str, ...] = ()

    def matches(self, key: str) -> bool:
        k = normalize_key(key)
        if any(stem in k for stem in self.exclude):
            return False
        return any(all(stem in k for stem in variant) for variant in self.variants)


@dataclass(frozen=True)
class Category:
    code: str
    title: str
    keywords: tuple[str, ...]
    expected: tuple[ExpectedField, ...] = field(default_factory=tuple)


def normalize_key(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


GOSREESTR = ExpectedField("Номер в Госреестре СИ", (("госреестр",), ("реестр", "си")))
INTERVAL = ExpectedField("Межповерочный интервал", (("межповер",), ("поверк", "интервал")))
DIMENSIONS = ExpectedField("Габаритные размеры", (("габарит",), ("размер",)))

CATEGORIES: tuple[Category, ...] = (
    Category(
        code="manometer",
        title="Манометр",
        keywords=("манометр", "мановакуумметр", "вакуумметр", "напоромер", "тягомер"),
        expected=(
            ExpectedField("Диапазон измерений", (("диапазон",),)),
            ExpectedField("Класс точности", (("класс", "точност"),)),
            ExpectedField("Присоединение", (("присоедин",), ("резьб",))),
            ExpectedField("Диаметр корпуса", (("диаметр",),)),
            ExpectedField("Степень защиты (IP)", (("степень", "защит"), ("ip",))),
            ExpectedField("Температура измеряемой среды", (("температур",),)),
            GOSREESTR,
            INTERVAL,
        ),
    ),
    Category(
        code="hygrometer",
        title="Гигрометр / психрометр",
        keywords=("гигрометр", "психрометр", "влагомер воздуха"),
        expected=(
            ExpectedField("Диапазон измерения влажности", (("диапазон", "влаж"),), exclude=("температурн",)),
            ExpectedField("Диапазон измерения температуры", (("диапазон", "температур"),), exclude=("влаж",)),
            ExpectedField("Погрешность измерения", (("погрешн",),)),
            ExpectedField("Цена деления шкалы", (("цена", "делен"),)),
            DIMENSIONS,
            GOSREESTR,
            INTERVAL,
        ),
    ),
    Category(
        code="plc",
        title="Программируемый логический контроллер",
        keywords=("контроллер", "плк"),
        expected=(
            ExpectedField("Напряжение питания", (("напряжен", "питан"),)),
            ExpectedField("Центральный процессор", (("процессор",),)),
            ExpectedField("Оперативная память", (("оператив",), ("озу",), ("ram",))),
            ExpectedField("Дискретные входы", (("дискретн", "вход"),)),
            ExpectedField("Дискретные выходы", (("дискретн", "выход"),)),
            ExpectedField("Аналоговые входы", (("аналогов", "вход"),)),
            ExpectedField("Интерфейсы связи", (("интерфейс",), ("ethernet",), ("rs-485",), ("rs485",))),
            ExpectedField("Среда программирования", (("сред", "программ"), ("codesys",))),
            ExpectedField("Степень защиты корпуса", (("степень", "защит"),)),
            ExpectedField("Диапазон рабочих температур", (("температур",),)),
            ExpectedField("Способ монтажа", (("монтаж",), ("креплен",), ("din",))),
            DIMENSIONS,
        ),
    ),
)

GENERIC = Category(code="generic", title="Прочее оборудование КИПиА", keywords=())


def detect_category(name: str) -> Category:
    text = normalize_key(name)
    for category in CATEGORIES:
        if any(word in text for word in category.keywords):
            return category
    return GENERIC


def find_missing(category: Category, available_keys: list[str]) -> list[str]:
    """Ожидаемые для категории поля, которых нет среди available_keys."""
    return [
        exp.title
        for exp in category.expected
        if not any(exp.matches(key) for key in available_keys)
    ]
