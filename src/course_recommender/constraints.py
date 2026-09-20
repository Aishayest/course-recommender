"""Жёсткие ограничения handbook.

Это не ML: пререквизиты, кредиты и квоты — детерминированные правила.
Модель ранжирует только то, что прошло этот фильтр.
"""

from __future__ import annotations

from .domain import Course, CourseKind, Requirement, Student


def prerequisites_met(course: Course, student: Student) -> bool:
    """Выполнены ли пререквизиты курса.

    Пререквизиты заданы как КНФ: внешний список — И, внутренний — ИЛИ.
    """
    done = student.completed_codes
    return all(any(code in done for code in group) for group in course.prerequisites)


def is_eligible(course: Course, student: Student, semester: int) -> bool:
    """Может ли студент вообще записаться на курс в этом семестре."""
    if course.code in student.completed_codes:
        return False
    if course.semesters_offered and semester not in course.semesters_offered:
        return False
    return prerequisites_met(course, student)


def eligible_courses(
    catalog: list[Course], student: Student, semester: int
) -> list[Course]:
    """Все допустимые курсы — вход для этапа ранжирования."""
    return [c for c in catalog if is_eligible(c, student, semester)]


def remaining_requirements(
    requirements: list[Requirement],
    catalog: dict[str, Course],
    student: Student,
) -> dict[CourseKind, int]:
    """Сколько кредитов каждой категории студенту ещё не хватает."""
    earned: dict[CourseKind, int] = {}
    for completed in student.completed:
        course = catalog.get(completed.code)
        if course is None:
            continue
        earned[course.kind] = earned.get(course.kind, 0) + course.credits

    remaining: dict[CourseKind, int] = {}
    for req in requirements:
        gap = req.required_credits - earned.get(req.kind, 0)
        if gap > 0:
            remaining[req.kind] = gap
    return remaining


def covers_requirement(
    course: Course, remaining: dict[CourseKind, int]
) -> bool:
    """Закрывает ли курс ещё не выполненное требование handbook."""
    return remaining.get(course.kind, 0) > 0
