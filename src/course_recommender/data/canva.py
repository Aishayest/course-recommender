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
class Block:
    """Элемент страницы с координатами.

    Порядок элементов в JSON не совпадает с визуальным, поэтому геометрия
    обязательна: только по ней таблица плана связывается с заголовком
    "YEAR N" над ней и с названием специальности.
    """

    kind: str  # "text" | "table"
    top: float
    left: float
    width: float = 0.0
    height: float = 0.0
    text: str = ""
    table: Table | None = None

    @property
    def right(self) -> float:
        return self.left + self.width

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2


@dataclass
class Page:
    """Страница презентации: блоки отсортированы сверху вниз."""

    number: int
    blocks: list[Block] = field(default_factory=list)

    @property
    def texts(self) -> list[str]:
        return [b.text for b in self.blocks if b.kind == "text"]

    @property
    def tables(self) -> list[Table]:
        return [b.table for b in self.blocks if b.kind == "table" and b.table]


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


def _geometry(element: dict) -> tuple[float, float, float, float]:
    """Геометрия элемента: A — сверху, B — слева, D — ширина, C — высота."""

    def number(key: str) -> float:
        value = element.get(key)
        return float(value) if isinstance(value, (int, float)) else 0.0

    return number("A"), number("B"), number("D"), number("C")


def parse_pages(bootstrap: dict) -> list[Page]:
    """Разобрать дизайн на страницы с блоками, упорядоченными сверху вниз."""
    raw_pages = bootstrap["page"]["Bj"]["A"]["D"]["A"]["A"]
    pages: list[Page] = []
    for index, raw_page in enumerate(raw_pages, start=1):
        blocks: list[Block] = []
        for element in raw_page.get("E", []):
            if not isinstance(element, dict):
                continue
            top, left, width, height = _geometry(element)
            table = _table_of(element)
            if table is not None:
                blocks.append(Block("table", top, left, width, height, table=table))
                continue
            text = _text_of(element)
            if text:
                blocks.append(Block("text", top, left, width, height, text=text))
        blocks.sort(key=lambda b: (b.top, b.left))
        pages.append(Page(number=index, blocks=blocks))
    return pages


def parse_url(url: str) -> list[Page]:
    return parse_pages(extract_bootstrap(fetch_html(url)))


def to_dict(pages: list[Page]) -> list[dict]:
    return [
        {
            "page": page.number,
            "blocks": [
                {
                    "kind": block.kind,
                    "top": round(block.top, 2),
                    "left": round(block.left, 2),
                    "width": round(block.width, 2),
                    "height": round(block.height, 2),
                    **({"text": block.text} if block.kind == "text" else {}),
                    **({"rows": block.table.rows} if block.table else {}),
                }
                for block in page.blocks
            ],
        }
        for page in pages
    ]


def from_dict(payload: list[dict]) -> list[Page]:
    """Обратная операция: восстановить страницы из сохранённого JSON."""
    pages: list[Page] = []
    for raw_page in payload:
        blocks = [
            Block(
                kind=b["kind"],
                top=b["top"],
                left=b["left"],
                width=b.get("width", 0.0),
                height=b.get("height", 0.0),
                text=b.get("text", ""),
                table=Table(rows=b["rows"]) if "rows" in b else None,
            )
            for b in raw_page["blocks"]
        ]
        pages.append(Page(number=raw_page["page"], blocks=blocks))
    return pages


def load(path: Path) -> list[Page]:
    return from_dict(json.loads(path.read_text(encoding="utf-8")))


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
