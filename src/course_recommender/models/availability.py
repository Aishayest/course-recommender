"""Вероятность получить место на курсе.

Главная боль: handbook говорит одно, а на регистрации приоритет уходит
старшим курсам и высокому GPA. Обычная бинарная классификация —
P(студент получит место | курс, семестр).
"""

from __future__ import annotations

import numpy as np

from ..domain import Course, Student


class AvailabilityModel:
    """LightGBM поверх табличных признаков регистрации."""

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        raise NotImplementedError("нужны исторические записи о регистрации")

    def predict_proba(self, student: Student, courses: list[Course]) -> np.ndarray:
        raise NotImplementedError("нужны исторические записи о регистрации")
