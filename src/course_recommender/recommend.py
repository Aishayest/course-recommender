"""Сборка пайплайна: handbook -> кандидаты -> ранжирование -> портфель.

Итоговая рекомендация — не топ по релевантности, а портфель с учётом
риска: основной курс плюс запасной, закрывающий то же требование.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import UTILITY_WEIGHTS
from .domain import Course, Student


@dataclass
class Recommendation:
    """Рекомендованный курс с объяснением и запасным вариантом."""

    course: Course
    score: float
    relevance: float
    availability: float
    expected_grade: float
    covers: str
    fallback: Course | None = None


def utility(relevance: float, availability: float, expected_grade: float) -> float:
    """Взвешенная полезность курса."""
    w = UTILITY_WEIGHTS
    return (
        w["relevance"] * relevance
        + w["availability"] * availability
        + w["grade"] * expected_grade
    )


def recommend(
    student: Student, catalog: list[Course], semester: int
) -> list[Recommendation]:
    """Полный проход: фильтр handbook, отбор кандидатов, ранжирование."""
    raise NotImplementedError("собираем, когда будут готовы слои модели")
