"""Доменная модель: курсы, студенты, требования handbook."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Буквенные оценки NU в баллах GPA.
GRADE_POINTS: dict[str, float] = {
    "A": 4.00,
    "A-": 3.67,
    "B+": 3.33,
    "B": 3.00,
    "B-": 2.67,
    "C+": 2.33,
    "C": 2.00,
    "C-": 1.67,
    "D+": 1.33,
    "D": 1.00,
    "F": 0.00,
}


def grade_points(letter: str | None) -> float | None:
    """Балл по буквенной оценке."""
    return GRADE_POINTS.get(letter) if letter else None


class CourseKind(str, Enum):
    """Категория курса в handbook."""

    CORE = "core"
    MAJOR = "major"
    MINOR = "minor"
    ELECTIVE = "elective"
    # Курс есть в плане, но handbook не относит его явно ни к одной категории.
    # Лучше честно не знать, чем приписать не ту и посчитать кредиты неверно.
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Course:
    """Курс из каталога."""

    code: str
    title: str
    credits: int
    kind: CourseKind
    description: str = ""
    # Списком списков: внешний уровень — И, внутренний — ИЛИ.
    # [["MATH101"], ["CS102", "CS103"]] = MATH101 И (CS102 ИЛИ CS103).
    prerequisites: list[list[str]] = field(default_factory=list)
    semesters_offered: tuple[int, ...] = ()
    capacity: int | None = None
    # Минимальная оценка, с которой курс засчитывается в план.
    min_grade: str | None = None
    # Семестр, в котором курс стоит в рекомендованном плане (1..8).
    recommended_semester: int | None = None
    # Минимальная оценка по конкретному пререквизиту: ECON 101 сам по себе
    # сдаётся на C-, но как пререквизит к ECON 201 требует B-.
    prerequisite_min_grades: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletedCourse:
    """Пройденный студентом курс с оценкой."""

    code: str
    grade: float  # GPA-шкала 0.0–4.0
    semester: int


@dataclass
class Student:
    """Состояние студента на момент выбора курсов."""

    student_id: str
    major: str
    year: int
    gpa: float
    completed: list[CompletedCourse] = field(default_factory=list)

    @property
    def completed_codes(self) -> set[str]:
        return {c.code for c in self.completed}

    def grade_of(self, code: str) -> float | None:
        """Оценка за пройденный курс, если он пройден."""
        for course in self.completed:
            if course.code == code:
                return course.grade
        return None

    @property
    def earned_credits(self) -> int:
        raise NotImplementedError("нужен каталог для подсчёта кредитов")


@dataclass(frozen=True)
class Requirement:
    """Требование handbook: сколько кредитов какой категории нужно набрать."""

    kind: CourseKind
    required_credits: int
    # Если задано — засчитываются только курсы из этого списка.
    eligible_codes: frozenset[str] | None = None
