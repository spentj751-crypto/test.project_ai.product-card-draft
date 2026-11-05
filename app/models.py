from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NO_DATA = "данных нет"



class ProductInput(BaseModel):
    """Нормализованные данные о товаре (после разбора сырого JSON)."""

    name: str
    manufacturer: str | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    description: str = ""



class CommercialBlock(BaseModel):
    target_audience: list[str] = Field(description="Кому подходит прибор")
    tasks: list[str] = Field(description="Какие задачи решает")
    selling_points: list[str] = Field(description="Аргументы для менеджера, каждый опирается на факт из данных")


class ExtractedSpec(BaseModel):
    name: str
    value: str
    quote: str


class LLMDraft(BaseModel):
    """То, что ожидаем от LLM. Технические значения сюда попадают только
    через extracted_from_description — и только с дословной цитатой."""

    seo_title: str
    seo_description: str
    search_queries: list[str]
    commercial: CommercialBlock
    extracted_from_description: list[ExtractedSpec] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)



Source = Literal["input", "specs", "description", "missing"]


class Characteristic(BaseModel):
    name: str
    value: str
    source: Source
    quote: str | None = None


class CardMeta(BaseModel):
    model: str
    attempts: int
    generated_at: str
    duration_sec: float


class ProductCard(BaseModel):
    status: Literal["ok", "needs_review"]
    product_name: str
    category: str
    seo_title: str
    seo_title_length: int
    seo_description: str
    seo_description_length: int
    characteristics: list[Characteristic]
    search_queries: list[str]
    commercial: CommercialBlock
    missing_fields: list[str]
    clarification_questions: list[str]
    warnings: list[str]
    meta: CardMeta
