"""Content-based эмбеддинги курсов и студентов.

Коллаборативная фильтрация в универе страдает от разреженности и от того,
что handbook сам навязывает всем похожий набор. Поэтому основа —
описания курсов, а история студента даёт веса.
"""

from __future__ import annotations

import numpy as np

from ..domain import Course, Student


def embed_courses(courses: list[Course]) -> np.ndarray:
    """Эмбеддинги курсов из названия и описания."""
    raise NotImplementedError("подключить sentence-transformers")


def embed_student(
    student: Student, course_vectors: dict[str, np.ndarray]
) -> np.ndarray:
    """Профиль студента: пройденные курсы с весом по оценке."""
    raise NotImplementedError("зависит от embed_courses")
