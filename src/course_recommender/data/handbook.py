"""Разбор handbook в машиночитаемые требования.

Самая трудоёмкая часть проекта: handbook обычно PDF, и часть правил
придётся выписывать вручную. Результат — список Requirement и граф
пререквизитов.
"""

from __future__ import annotations

from pathlib import Path

from ..domain import Requirement


def load_requirements(path: Path, major: str) -> list[Requirement]:
    """Требования handbook для конкретной специальности."""
    raise NotImplementedError("ждём разбор handbook")
