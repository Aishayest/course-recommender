"""Извлечение handbook из Canva-презентации.

Canva рендерит дизайн на canvas, но весь текст при этом лежит в странице:
в <script> с `window['bootstrap'] = JSON.parse('...')`. Оттуда достаются и
обычные текстовые блоки, и таблицы — с сохранением строк и колонок, что для
handbook важнее всего: требования там оформлены таблицами.

Работает только с публичной ссылкой вида /design/<id>/<token>/view.

    python -m course_recommender.data.canva <url> -o data/raw/handbook_2023.json
"""

from __future__ import annotations

import json
import re
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from urllib.request import Request, urlopen

from ..config import HANDBOOK_SOURCES, handbook_path

BOOTSTRAP_START = "JSON.parse('"
CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


@dataclass
class Table:
    """Таблица со страницы: заголовок — первая строка."""

    rows: list[list[str]]

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> list[list[str]]:
        return self.rows[1:]


@dataclass
class Page:
    """Страница презентации."""

    number: int
    texts: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def _ssl_context() -> ssl.SSLContext:
    """Python с python.org не видит системные сертификаты macOS — берём certifi."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_html(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_bootstrap(html: str) -> dict:
    """Достать встроенный JSON дизайна из HTML."""
    start = html.find(BOOTSTRAP_START)
    if start == -1:
        raise ValueError("bootstrap JSON не найден — ссылка не публичная или Canva сменила формат")
    start += len(BOOTSTRAP_START)
    end = html.find("')", start)
    raw = html[start:end]
    # снимаем экранирование уровня JS-строки, дальше это валидный JSON
    return json.loads(re.sub(r"\\(['\\])", r"\1", raw))


def _runs(node: dict | None) -> list[str]:
    """Текстовые фрагменты узла: везде лежат по пути C -> A."""
    if not isinstance(node, dict):
        return []
    value = node.get("C", {}).get("A") if isinstance(node.get("C"), dict) else None
    return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []


def _text_of(element: dict) -> str:
    return "".join(_runs(element.get("a"))).strip()


def _table_of(element: dict) -> Table | None:
    """Собрать таблицу из ячеек вида A1, B2, C10."""
    cells = element.get("c")
    if not isinstance(cells, dict):
        return None

    grid: dict[tuple[int, str], str] = {}
    for ref, cell in cells.items():
        match = CELL_REF.match(ref)
        if not match or not isinstance(cell, dict):
            continue
        column, row = match.group(1), int(match.group(2))
        text = "".join(_runs(cell.get("B", {}).get("A"))).strip()
        grid[(row, column)] = text

    if not grid:
        return None

    columns = sorted({column for _, column in grid}, key=lambda c: (len(c), c))
    rows = sorted({row for row, _ in grid})
    return Table(rows=[[grid.get((r, c), "") for c in columns] for r in rows])


def parse_pages(bootstrap: dict) -> list[Page]:
    """Разобрать дизайн на страницы с текстом и таблицами."""
    raw_pages = bootstrap["page"]["Bj"]["A"]["D"]["A"]["A"]
    pages: list[Page] = []
    for index, raw_page in enumerate(raw_pages, start=1):
        page = Page(number=index)
        for element in raw_page.get("E", []):
            if not isinstance(element, dict):
                continue
            table = _table_of(element)
            if table is not None:
                page.tables.append(table)
                continue
            text = _text_of(element)
            if text:
                page.texts.append(text)
        pages.append(page)
    return pages


def parse_url(url: str) -> list[Page]:
    return parse_pages(extract_bootstrap(fetch_html(url)))


def to_dict(pages: list[Page]) -> list[dict]:
    return [
        {
            "page": page.number,
            "texts": page.texts,
            "tables": [table.rows for table in page.tables],
        }
        for page in pages
    ]


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Выгрузить handbook из Canva в JSON")
    parser.add_argument("url", nargs="?", help="публичная ссылка на дизайн Canva")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--all", action="store_true", help="выгрузить все годы из config.HANDBOOK_SOURCES"
    )
    args = parser.parse_args()

    if args.all:
        targets = [(year, url, handbook_path(year)) for year, url in HANDBOOK_SOURCES.items()]
    elif args.url and args.output:
        targets = [(None, args.url, args.output)]
    else:
        parser.error("нужно указать url и -o, либо --all")

    for year, url, output in targets:
        pages = parse_url(url)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(to_dict(pages), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tables = sum(len(p.tables) for p in pages)
        label = f"{year}: " if year else ""
        print(f"{label}{len(pages)} страниц, {tables} таблиц -> {output}")


if __name__ == "__main__":
    main()
