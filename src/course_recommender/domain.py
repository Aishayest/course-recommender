"""Доменная модель: курсы, студенты, требования handbook."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CourseKind(str, Enum):
    """Категория курса в handbook."""

    CORE = "core"
    MAJOR = "major"
    MINOR = "minor"
    ELECTIVE = "elective"


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
