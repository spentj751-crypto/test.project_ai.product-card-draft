import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MANOMETER = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {
        "диапазон измерений": "0–1,6 МПа",
        "класс точности": "1,5",
        "присоединение": "G1/2",
        "диаметр корпуса": "100 мм",
    },
    "description": "Прибор предназначен для измерения избыточного давления.",
}


def seo_text(target: int = 1000) -> str:
    """Текст нужной длины только с числами из MANOMETER."""
    sentence = (
        "Манометр показывающий DM 02 производства Манотомь предназначен для измерения "
        "избыточного давления в диапазоне 0–1,6 МПа, класс точности 1,5. "
    )
    text = ""
    while len(text) + len(sentence) <= target:
        text += sentence
    return text.strip()


def make_draft(**overrides) -> dict:
    draft = {
        "seo_title": "Манометр показывающий DM 02 Манотомь 0–1,6 МПа",
        "seo_description": seo_text(),
        "search_queries": ["манометр dm 02", "манометр манотомь", "манометр 1,6 мпа g1/2"],
        "commercial": {
            "target_audience": ["службы КИПиА", "монтажные организации"],
            "tasks": ["контроль избыточного давления"],
            "selling_points": ["класс точности 1,5", "присоединение G1/2"],
        },
        "extracted_from_description": [],
        "clarification_questions": ["Какая степень защиты корпуса?"],
    }
    draft.update(overrides)
    return draft


class FakeLLM:
    """Возвращает заранее заданные ответы по очереди и запоминает запросы."""

    model = "fake-llm"

    def __init__(self, *responses):
        self.responses = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in responses]
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        self.calls.append(list(messages))
        if len(self.calls) > len(self.responses):
            return self.responses[-1]
        return self.responses[len(self.calls) - 1]


@pytest.fixture
def manometer():
    return json.loads(json.dumps(MANOMETER, ensure_ascii=False))
