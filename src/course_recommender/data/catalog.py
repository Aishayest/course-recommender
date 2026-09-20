"""Каталог курсов: парсинг с сайта университета и загрузка на диск."""

from __future__ import annotations

from pathlib import Path

from ..domain import Course


def load_catalog(path: Path) -> list[Course]:
    """Прочитать каталог курсов из обработанного файла."""
    raise NotImplementedError("ждём выгрузку каталога в data/processed")


def scrape_catalog(base_url: str) -> list[Course]:
    """Собрать каталог с сайта университета."""
    raise NotImplementedError("нужен URL каталога")
