"""Реранкер поверх отобранных кандидатов."""

from __future__ import annotations

import numpy as np

from ..domain import Course, Student


def build_features(
    student: Student, courses: list[Course]
) -> np.ndarray:
    """Признаки пары (студент, курс): близость, покрытие handbook, нагрузка."""
    raise NotImplementedError("зависит от эмбеддингов и каталога")


class Reranker:
    """LightGBM ranker, обучается на фактических выборах студентов."""

    def fit(self, X: np.ndarray, y: np.ndarray, groups: np.ndarray) -> None:
        raise NotImplementedError("нужны исторические выборы курсов")

    def predict(self, X: np.ndarray) -> np.ndarray:
        raise NotImplementedError("нужны исторические выборы курсов")
