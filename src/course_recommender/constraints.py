"""Жёсткие ограничения handbook.

Это не ML: пререквизиты, кредиты и квоты — детерминированные правила.
Модель ранжирует только то, что прошло этот фильтр.
"""

from __future__ import annotations

from .domain import Course, CourseKind, Requirement, Student, grade_points


def passed_with(student: Student, code: str, min_grade: str | None) -> bool:
    """Пройден ли курс с достаточной оценкой.

    Сдать курс мало: handbook требует по ряду пререквизитов оценку выше
    проходной, и слабая оценка закрывает дорогу к следующему курсу.
    """
    earned = student.grade_of(code)
    if earned is None:
        return False
    required = grade_points(min_grade)
    return required is None or earned >= required


def prerequisites_met(course: Course, student: Student) -> bool:
    """Выполнены ли пререквизиты курса, с учётом минимальных оценок.

    Пререквизиты заданы как КНФ: внешний список — И, внутренний — ИЛИ.
    """
    return all(
        any(
            passed_with(student, code, course.prerequisite_min_grades.get(code))
            for code in group
        )
        for group in course.prerequisites
    )


def is_eligible(course: Course, student: Student, semester: int) -> bool:
    """Может ли студент вообще записаться на курс в этом семестре."""
    if course.code in student.completed_codes:
        return False
    if course.semesters_offered and semester not in course.semesters_offered:
        return False
    return prerequisites_met(course, student)


def eligible_courses(
    catalog: list[Course], student: Student, semester: int, respect_plan: bool = False
) -> list[Course]:
    """Все допустимые курсы — вход для этапа ранжирования.

    respect_plan отсекает курсы, стоящие в плане позже текущего семестра.
    Это временная замена графу пререквизитов: без него второкурснику
    формально доступен Senior Project с четвёртого курса. Когда появится
    каталог с настоящими пререквизитами, фильтр станет не нужен.
    """
    courses = [c for c in catalog if is_eligible(c, student, semester)]
    if respect_plan:
        courses = [
            c
            for c in courses
            if c.recommended_semester is None or c.recommended_semester <= semester
        ]
    return courses


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
