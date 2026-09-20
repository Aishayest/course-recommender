"""Исторические транскрипты и записи о регистрации.

Персональные данные: в репозиторий не попадают, только анонимизированно
и локально в data/raw. Если доступа к реальным данным не будет —
здесь же генерируем синтетические траектории из handbook.
"""

from __future__ import annotations

from pathlib import Path

from ..domain import Student


def load_students(path: Path) -> list[Student]:
    """Анонимизированные транскрипты."""
    raise NotImplementedError("ждём выгрузку транскриптов")


def generate_synthetic(n_students: int, seed: int = 42) -> list[Student]:
    """Синтетические траектории — запасной план, если данных не дадут."""
    raise NotImplementedError("реализуем, когда прояснится доступ к данным")
