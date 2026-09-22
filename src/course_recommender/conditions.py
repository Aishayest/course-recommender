"""Условия допуска к курсу.

Пререквизиты университета — это не список кодов, а булево выражение с AND, OR
и вложенными скобками, где у каждого курса свой порог оценки. Здесь описано
само дерево условий и его вычисление; разбор текста в это дерево живёт в
data/registration.py.

Вычисление трёхзначное. Про баллы IELTS и уровень казахского в транскрипте
ничего нет, и честнее вернуть "неизвестно", чем объявить курс недоступным:
иначе ASC 200 пропал бы у всех, кто прошёл по языковому тесту, а не по курсу.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .domain import Student, grade_points


@dataclass(frozen=True)
class CourseNeeded:
    """Пройденный курс как условие."""

    code: str
    title: str = ""
    catalog_id: str = ""
    min_grade: str | None = None
    outcome: str | None = None  # "P" — зачтено, "F" — только как антиреквизит

    def __str__(self) -> str:
        if self.outcome:
            return f"{self.code} ({self.outcome})"
        return f"{self.code} ≥ {self.min_grade}" if self.min_grade else self.code


@dataclass(frozen=True)
class SubjectRange:
    """Любой курс предмета в диапазоне номеров: Subject "HST" BETWEEN 200 and 299."""

    subject: str
    low: int
    high: int

    def __str__(self) -> str:
        return f"{self.subject} {self.low}-{self.high}"


@dataclass(frozen=True)
class ExamScore:
    """Балл теста: Test "IELTS" BETWEEN 6.5 and 9.

    Без префикса Test в имени: pytest принял бы такой класс за набор тестов.
    """

    name: str
    low: float
    high: float

    def __str__(self) -> str:
        return f"{self.name} {self.low}-{self.high}"


@dataclass(frozen=True)
class Placement:
    """Уровень по результатам размещения: KLL "[C1.1] Advanced"."""

    scale: str
    level: str
    label: str = ""

    def __str__(self) -> str:
        return f"{self.scale} {self.level}"


@dataclass(frozen=True)
class All:
    """Все условия сразу (AND)."""

    terms: tuple

    def __str__(self) -> str:
        return "(" + " AND ".join(str(t) for t in self.terms) + ")"


@dataclass(frozen=True)
class Any:
    """Хотя бы одно условие (OR)."""

    terms: tuple

    def __str__(self) -> str:
        return "(" + " OR ".join(str(t) for t in self.terms) + ")"


# Любой узел дерева условий.
Requirement = CourseNeeded | SubjectRange | ExamScore | Placement | All | Any


def evaluate(node, student: Student, known_tests: dict[str, float] | None = None) -> bool | None:
    """Выполнено ли условие: True, False или None, если данных не хватает."""
    if node is None:
        return True

    if isinstance(node, All):
        results = [evaluate(t, student, known_tests) for t in node.terms]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True

    if isinstance(node, Any):
        results = [evaluate(t, student, known_tests) for t in node.terms]
        if any(r is True for r in results):
            return True
        return None if any(r is None for r in results) else False

    if isinstance(node, CourseNeeded):
        earned = student.grade_of(node.code)
        if node.outcome == "F":
            # Антиреквизит по F: выполнен только при явно проваленном курсе.
            return earned is not None and earned == 0.0
        if earned is None:
            return False
        if node.outcome == "P":
            return True
        required = grade_points(node.min_grade)
        return required is None or earned >= required

    if isinstance(node, SubjectRange):
        for course in student.completed:
            parts = course.code.split()
            if (
                len(parts) == 2
                and parts[0] == node.subject
                and parts[1][:3].isdigit()
                and node.low <= int(parts[1][:3]) <= node.high
            ):
                return True
        return False

    if isinstance(node, ExamScore):
        score = (known_tests or {}).get(node.name)
        return None if score is None else node.low <= score <= node.high

    if isinstance(node, Placement):
        return None

    return None


def course_codes(node) -> set[str]:
    """Все коды курсов в условии — для построения графа зависимостей."""
    if node is None:
        return set()
    if isinstance(node, (All, Any)):
        return set().union(*(course_codes(t) for t in node.terms)) if node.terms else set()
    if isinstance(node, CourseNeeded):
        return {node.code}
    return set()


# Узлы дерева по имени — для чтения условий с диска.
NODE_TYPES = {
    cls.__name__: cls for cls in (CourseNeeded, SubjectRange, ExamScore, Placement, All, Any)
}


def to_json(node):
    """Дерево условий в JSON-совместимую структуру.

    Строковое представление здесь не годится: str(node) читается человеком,
    но разобрать его обратно нельзя, а каталог курсов должен переживать
    сохранение на диск без потери условий допуска.
    """
    if node is None:
        return None
    payload = {"type": type(node).__name__}
    for field in fields(node):
        value = getattr(node, field.name)
        payload[field.name] = (
            [to_json(term) for term in value] if field.name == "terms" else value
        )
    return payload


def from_json(data):
    """Дерево условий обратно из JSON."""
    if data is None:
        return None
    node = NODE_TYPES[data["type"]]
    values = {key: value for key, value in data.items() if key != "type"}
    if "terms" in values:
        values["terms"] = tuple(from_json(term) for term in values["terms"])
    return node(**values)
