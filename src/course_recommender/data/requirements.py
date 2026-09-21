"""Разбор таблиц требований handbook.

Планы (handbook.py) показывают рекомендуемую последовательность курсов, но
не все специальности расписаны на четыре года: у SSH расписан только первый
курс, а остальное задано таблицей требований. Она же даёт то, чего в планах
нет вовсе — сколько кредитов нужно набрать по каждой категории.

Встречаются две формы:

    Anthropology requirements | Credits | Explanation   — категория + правило
    MAJOR requirements        | Credits                 — явный список курсов

Обе сводятся к RequirementRow. Внутри одной таблицы бывает несколько секций:
строка "Core requirements | Credits | Explanation" внутри тела означает, что
дальше идут общеуниверситетские требования, а не профильные.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain import CourseKind, Requirement
from .canva import Page, Table
from .handbook import COURSE_CODE, CourseRef, is_plan_table, normalize, parse_program_heading

SECTION_HEADER = re.compile(r"^(.+?)\s+requirements$", re.IGNORECASE)
TOTAL_ROW = re.compile(r"^total\b", re.IGNORECASE)
# В handbook оценка в кавычках и с пробелом перед знаком: "C -" or above.
MIN_GRADE = re.compile(
    r'["“]?\s*([A-D]\s*[+-]?)\s*["”]?\s*(?:or\s+(?:above|higher|better))', re.IGNORECASE
)
LEVEL = re.compile(r"(\d)00[-\s]?level", re.IGNORECASE)
CHOICE_PREFIX = re.compile(r"choice of\s*:?\s*", re.IGNORECASE)
REQUIRED_PREFIX = re.compile(r"required\s*:?\s*", re.IGNORECASE)
BARE_NUMBER = re.compile(r"\b(\d{3}[A-Z]?)\b")

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
COUNT_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)

# Названия категорий -> категория курса в доменной модели.
ELECTIVE_HINTS = ("elective", "open box", "any courses")


@dataclass
class RequirementRow:
    """Строка таблицы требований."""

    admission_year: int
    program: str
    section: str  # "major" | "core" | иное из заголовка секции
    name: str
    credits: int | None
    explanation: str = ""
    courses: list[CourseRef] = field(default_factory=list)
    choices: list[list[str]] = field(default_factory=list)
    count: int | None = None
    min_level: int | None = None
    min_grade: str | None = None
    is_total: bool = False

    @property
    def kind(self) -> CourseKind:
        """Категория handbook в терминах доменной модели."""
        name = self.name.lower()
        if any(hint in name for hint in ELECTIVE_HINTS):
            return CourseKind.ELECTIVE
        return CourseKind.MAJOR if self.section == "major" else CourseKind.CORE


def expand_codes(text: str) -> list[str]:
    """Коды курсов, включая сокращённую запись.

    "One Ethics course (PHIL 210, 211 or 212)" -> PHIL 210, PHIL 211, PHIL 212:
    у второго и третьего номера префикс опущен, он наследуется от первого.
    """
    text = normalize(text)
    codes: list[str] = []
    prefix: str | None = None
    position = 0

    while position < len(text):
        full = COURSE_CODE.search(text, position)
        bare = BARE_NUMBER.search(text, position)
        if full and (not bare or full.start() <= bare.start()):
            prefix = full.group(1)
            codes.append(f"{prefix} {full.group(2)}")
            position = full.end()
        elif bare:
            if prefix:
                codes.append(f"{prefix} {bare.group(1)}")
            position = bare.end()
        else:
            break
    return codes


def parse_count(text: str) -> int | None:
    """Сколько курсов требуется: "Any four ANT electives" -> 4."""
    match = COUNT_WORD.search(normalize(text))
    return NUMBER_WORDS[match.group(1).lower()] if match else None


def parse_min_level(text: str) -> int | None:
    """Минимальный уровень курса: "200-level or above" -> 200."""
    match = LEVEL.search(normalize(text))
    return int(match.group(1)) * 100 if match else None


def parse_min_grade(text: str) -> str | None:
    """Минимальная оценка из примечания: 'passed with "C-" or above'."""
    match = MIN_GRADE.search(normalize(text))
    return match.group(1).replace(" ", "") if match else None


def parse_choices(text: str) -> list[list[str]]:
    """Группы выбора: "Choice of: A, B or C" и коды в скобках."""
    text = normalize(text)
    groups: list[list[str]] = []

    for fragment in re.findall(r"\(([^)]*)\)", text):
        codes = expand_codes(fragment)
        if len(codes) > 1:
            groups.append(codes)

    match = CHOICE_PREFIX.search(text)
    if match:
        codes = expand_codes(text[match.end() :])
        if codes:
            groups.append(codes)
    return groups


def _is_section_header(row: list[str]) -> str | None:
    """Строка-заголовок секции внутри таблицы."""
    match = SECTION_HEADER.match(normalize(row[0]))
    if not match or len(row) < 2 or not normalize(row[1]).lower().startswith("credit"):
        return None
    return match.group(1).strip().lower()


def _credits(cell: str) -> int | None:
    digits = re.findall(r"\d+", normalize(cell))
    return int(digits[0]) if digits else None


def is_requirement_table(table: Table) -> bool:
    """Таблица требований, а не план и не справочная."""
    return (
        not is_plan_table(table)
        and len(table.header) >= 2
        and _is_section_header(table.header) is not None
    )


def parse_requirement_table(
    table: Table, admission_year: int, program: str
) -> list[RequirementRow]:
    """Разобрать одну таблицу требований, включая вложенные секции."""
    section = _is_section_header(table.header) or "major"
    # "Anthropology requirements" -> major, "Core requirements" -> core
    section = "core" if section.startswith("core") else "major"

    rows: list[RequirementRow] = []
    for raw in table.body:
        if not raw or not normalize(raw[0]):
            continue
        nested = _is_section_header(raw)
        if nested:
            section = "core" if nested.startswith("core") else "major"
            continue

        name = normalize(raw[0])
        explanation = normalize(raw[2]) if len(raw) > 2 else ""
        source = f"{name} {explanation}".strip()
        rows.append(
            RequirementRow(
                admission_year=admission_year,
                program=program,
                section=section,
                name=name,
                credits=_credits(raw[1]) if len(raw) > 1 else None,
                explanation=explanation,
                courses=[CourseRef(code=code, title="") for code in expand_codes(source)],
                choices=parse_choices(source),
                count=parse_count(source),
                min_level=parse_min_level(source),
                min_grade=parse_min_grade(source),
                is_total=bool(TOTAL_ROW.match(name)),
            )
        )
    return rows


def parse_requirements(pages: list[Page], admission_year: int) -> list[RequirementRow]:
    """Собрать требования всех специальностей из handbook."""
    rows: list[RequirementRow] = []
    program: str | None = None

    for page in pages:
        for block in page.blocks:
            if block.kind == "text":
                heading = parse_program_heading(block.text)
                if heading:
                    program = heading[1]
                continue
            table = block.table
            if table is None or program is None or not is_requirement_table(table):
                continue
            rows.extend(parse_requirement_table(table, admission_year, program))
    return rows


def to_requirements(rows: list[RequirementRow]) -> list[Requirement]:
    """Свести строки к доменным Requirement, отбросив итоговые."""
    return [
        Requirement(kind=row.kind, required_credits=row.credits)
        for row in rows
        if not row.is_total and row.credits
    ]


def degree_credits(rows: list[RequirementRow]) -> int | None:
    """Всего кредитов на диплом — из строки "Total Degree Credits"."""
    for row in rows:
        if row.is_total and "degree" in row.name.lower() and row.credits:
            return row.credits
    return None
