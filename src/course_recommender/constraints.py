"""Жёсткие ограничения handbook.

Это не ML: пререквизиты, кредиты и квоты — детерминированные правила.
Модель ранжирует только то, что прошло этот фильтр.
"""

from __future__ import annotations

from .conditions import evaluate
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


def prerequisites_met(
    course: Course,
    student: Student,
    known_tests: dict[str, float] | None = None,
    allow_unknown: bool = True,
) -> bool:
    """Выполнены ли пререквизиты курса.

    Если у курса есть условие из документа регистрации, считаем по нему:
    это настоящее дерево AND/OR с порогом оценки по каждому курсу. Иначе
    остаётся приближение из handbook — КНФ, где внешний список это И,
    а внутренний ИЛИ.

    allow_unknown решает судьбу третьего значения: по умолчанию курс с
    непроверяемым условием (балл IELTS, уровень казахского) остаётся
    доступным, потому что отсечь его означало бы соврать студенту, который
    вошёл по языковому тесту.
    """
    if course.requirement is not None:
        result = evaluate(course.requirement, student, known_tests)
        return result is not False if allow_unknown else result is True

    return all(
        any(
            passed_with(student, code, course.prerequisite_min_grades.get(code))
            for code in group
        )
        for group in course.prerequisites
    )


def is_eligible(
    course: Course,
    student: Student,
    semester: int,
    known_tests: dict[str, float] | None = None,
) -> bool:
    """Может ли студент вообще записаться на курс в этом семестре."""
    if course.code in student.completed_codes:
        return False
    if course.semesters_offered and semester not in course.semesters_offered:
        return False
    return prerequisites_met(course, student, known_tests)


def eligible_courses(
    catalog: list[Course],
    student: Student,
    semester: int,
    respect_plan: bool = False,
    known_tests: dict[str, float] | None = None,
) -> list[Course]:
    """Все допустимые курсы — вход для этапа ранжирования.

    respect_plan — запасная мера для курсов, про которые настоящих условий
    нет: документ регистрации выходит на один семестр, поэтому у весенних
    курсов пререквизиты неизвестны, и без подстраховки второкурснику
    формально доступен Senior Project с четвёртого курса. Там, где условие
    известно, позиция в плане не учитывается: студент вправе идти с
    опережением, если выполнил пререквизиты.
    """
    courses = [c for c in catalog if is_eligible(c, student, semester, known_tests)]
    if respect_plan:
        courses = [
            c
            for c in courses
            if c.requirement is not None
            or c.recommended_semester is None
            or c.recommended_semester <= semester
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
