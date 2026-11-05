from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import ConfigError, Settings
from .input_parser import InputError
from .llm import LLMError, OpenAICompatibleClient
from .render import to_markdown
from .service import generate_card, prepare


def _load_items(path: str) -> list[tuple[str, str | dict]]:
    """Возвращает [(имя, данные)]. Файл с JSON-массивом даёт несколько товаров."""
    if path == "-":
        text, stem = sys.stdin.read(), "stdin"
    else:
        p = Path(path)
        text, stem = p.read_text(encoding="utf-8"), p.stem
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [(stem, text)]  # пусть parse_input сформулирует ошибку
    if isinstance(data, list):
        return [(f"{stem}-{i}", item) for i, item in enumerate(data, 1)]
    return [(stem, text)]


def _dry_run(name: str, data: str | dict) -> None:
    prepared = prepare(data)
    product = prepared.parsed.product
    print(f"=== {name} ===")
    print(f"Категория: {prepared.category.title}")
    print(f"Характеристик в specs: {len(product.specs)}, описание: {len(product.description)} симв.")
    if not product.manufacturer:
        print("Производитель: данных нет")
    if prepared.missing_expected:
        print("Нет ожидаемых для категории полей: " + ", ".join(prepared.missing_expected))
    for note in prepared.parsed.notes:
        print(f"Замечание: {note}")
    print("\n--- SYSTEM ---\n" + prepared.messages[0]["content"])
    print("--- USER ---\n" + prepared.messages[1]["content"] + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Генерация черновиков карточек товаров КИПиА по JSON.",
    )
    parser.add_argument("inputs", nargs="+", help="JSON-файлы с товарами ('-' — читать из stdin)")
    parser.add_argument("-o", "--out", help="папка для результатов (<имя>.json и <имя>.md)")
    parser.add_argument("--format", choices=["md", "json"], default="md", help="формат вывода в консоль без --out")
    parser.add_argument("--dry-run", action="store_true", help="не вызывать LLM: проверить вход и показать промпт")
    parser.add_argument("-v", "--verbose", action="store_true", help="подробный лог")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    items: list[tuple[str, str | dict]] = []
    failed = 0
    for path in args.inputs:
        try:
            items += _load_items(path)
        except OSError as exc:
            print(f"✗ {path}: не удалось прочитать файл ({exc.strerror})", file=sys.stderr)
            failed += 1

    if args.dry_run:
        for name, data in items:
            try:
                _dry_run(name, data)
            except InputError as exc:
                print(f"✗ {name}: {exc}", file=sys.stderr)
                failed += 1
        return 1 if failed else 0

    try:
        settings = Settings.from_env()
        llm = OpenAICompatibleClient(settings)
    except ConfigError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    for name, data in items:
        try:
            card = generate_card(data, llm, max_fix_attempts=settings.max_fix_attempts)
        except InputError as exc:
            print(f"✗ {name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        except LLMError as exc:
            print(f"✗ {name}: ошибка LLM — {exc}", file=sys.stderr)
            failed += 1
            continue

        if out_dir:
            (out_dir / f"{name}.json").write_text(
                json.dumps(card.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (out_dir / f"{name}.md").write_text(to_markdown(card), encoding="utf-8")
            mark = "✓" if card.status == "ok" else "!"
            print(
                f"{mark} {name}: {card.status}, заголовок {card.seo_title_length} симв., "
                f"описание {card.seo_description_length} симв., попыток {card.meta.attempts} "
                f"→ {out_dir / name}.json/.md"
            )
        elif args.format == "json":
            print(json.dumps(card.model_dump(), ensure_ascii=False, indent=2))
        else:
            print(to_markdown(card))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
