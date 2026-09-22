"""Разбор "Course Requirements and Registration Priorities".

Этот документ Registrar публикует перед каждой регистрацией, и он закрывает
две дыры, которых не было ни в handbook, ни в планах:

* настоящие пререквизиты — с логикой AND/OR, скобками и порогом по каждому
  курсу отдельно: ECON 201 требует ECON 101 на B-, хотя сам ECON 101 сдаётся
  на C-;
* тиры приоритета регистрации — кому место дают в первую очередь, кому во
  вторую и так далее. Это и есть та самая причина, по которой handbook
  советует одно, а на регистрации выходит другое.

Здесь только разбор текста в дерево условий; сами условия и их вычисление
живут в conditions.py. Приоритет AND выше, чем у OR, как в обычной логике:
в исходном тексте скобки расставлены не везде.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..conditions import All, Any, CourseNeeded, ExamScore, Placement, SubjectRange, course_codes

# Код курса: CSCI 151, NUSM 411a, NUR 406.1, WCS 150/ASC 100, WLL 102 /PHIL 102
CODE = r"[A-Z]{2,5}\s?\d{3}[A-Za-z]?(?:\.\d)?(?:\s*/\s*[A-Z]{2,5}\s?\d{3}[A-Za-z]?)?"
COURSE_ATOM = re.compile(rf"({CODE})\s+(.+?)\s*\((\d+)\)\s*\(([^)]*)\)")
SUBJECT_ATOM = re.compile(r'Subject\s+"([A-Z]+)"\s+BETWEEN\s+(\d+)\s+and\s+(\d+)')
TEST_ATOM = re.compile(r'Test\s+"([^"]+)"\s+BETWEEN\s+([\d.]+)\s+and\s+([\d.]+)')
PLACEMENT_ATOM = re.compile(r'([A-Z]{2,4})\s+"\[([^\]]+)\]\s*([^"]*)"')
GRADE = re.compile(r"^([A-D][+-]?)\s+and\s+above$")
AUDIENCE = re.compile(
    r"^(?:(\d)\s+year\s+)?(?:UG\s+)?(GSB|SCAI|SEDS|SMG|SoE|SoM|SOM|SSH)?\s*"
    r"(.*?)\s*(\(pending graduation\))?$"
)
PERMISSION = re.compile(r"instructor'?s permission", re.IGNORECASE)
SCHOOLS = {"GSB", "SCAI", "SEDS", "SMG", "SOE", "SOM", "SSH"}
# Школа SEDS разделилась на SCAI и SoE. Документы до 2026 знают только SEDS,
# и приоритет, выданный тогда всей школе, сегодня относится к студентам обеих.
# Связь односторонняя: приоритет, выданный сегодня SoE, на студента SCAI
# не распространяется.
SCHOOL_SUCCESSORS = {"SEDS": frozenset({"SCAI", "SOE"})}


@dataclass(frozen=True)
class Audience:
    """Кому положен приоритет: "3 year UG SSH Sociology"."""

    year: int | None = None
    school: str | None = None
    program: str | None = None
    pending_graduation: bool = False
    raw: str = ""

    def matches(self, year: int, school: str | None, program: str | None) -> bool:
        """Подходит ли студент под эту аудиторию.

        Пустое поле означает "любой": строка "SSH" покрывает всю школу,
        "Economics" — всех экономистов независимо от курса.
        """
        if self.year is not None and self.year != year:
            return False
        if self.school and not _same_school(self.school, school):
            return False
        return not (self.program and _norm(self.program) != _norm(program))


@dataclass
class CourseOffering:
    """Строка документа: курс с требованиями и приоритетами на семестр."""

    term: str
    school: str
    department: str
    code: str
    title: str
    credits_us: float | None = None
    credits_ects: int | None = None
    prerequisite: object | None = None
    corequisite: object | None = None
    antirequisite: object | None = None
    priorities: list[list[Audience]] = field(default_factory=list)
    instructor_permission: bool = False

    def priority_for(
        self, year: int, school: str | None, program: str | None, term: str | None = None
    ) -> int | None:
        """Тир приоритета студента: 1 — самый высокий, None — приоритета нет.

        Семестр здесь не спрашивается: строка описывает один семестр, свой
        собственный. Аргумент есть ради единообразия с каталогом, который
        хранит приоритеты по семестрам и умеет отдать нужный.
        """
        for tier, audiences in enumerate(self.priorities, start=1):
            if any(a.matches(year, school, program) for a in audiences):
                return tier
        return None


def _norm(value: str | None) -> str:
    """Сравнение названий специальностей.

    В handbook программа записана как "COMPUTER SCIENCE (CS)", а в документе
    регистрации — как "Computer Science". Скобочные уточнения и регистр
    отбрасываются, иначе приоритет не находится ни у одной программы.
    """
    if not value:
        return ""
    value = re.sub(r"\([^)]*\)", " ", value)
    return re.sub(r"\s+", " ", value).strip().upper()


def _same_school(audience: str | None, student: str | None) -> bool:
    """Та же ли это школа с поправкой на переименования."""
    named, actual = _norm(audience), _norm(student)
    return named == actual or actual in SCHOOL_SUCCESSORS.get(named, frozenset())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def _grade_of(raw: str) -> tuple[str | None, str | None]:
    """Разобрать условие в скобках: "C- and above" -> ("C-", None), "P" -> (None, "P")."""
    raw = raw.strip()
    match = GRADE.match(raw)
    if match:
        return match.group(1), None
    if raw in {"P", "F"}:
        return None, raw
    return None, None


def _atom_at(text: str, position: int):
    """Атом, начинающийся ровно с этой позиции, и его длина."""
    for pattern, build in (
        (COURSE_ATOM, _course_atom),
        (SUBJECT_ATOM, lambda m: SubjectRange(m.group(1), int(m.group(2)), int(m.group(3)))),
        (TEST_ATOM, lambda m: ExamScore(m.group(1), float(m.group(2)), float(m.group(3)))),
        (PLACEMENT_ATOM, lambda m: Placement(m.group(1), m.group(2), m.group(3).strip())),
    ):
        match = pattern.match(text, position)
        if match:
            return build(match), match.end()
    return None, position


def _course_atom(match: re.Match) -> CourseNeeded:
    grade, outcome = _grade_of(match.group(4))
    return CourseNeeded(
        code=re.sub(r"\s*/\s*", "/", normalize(match.group(1))),
        title=normalize(match.group(2)),
        catalog_id=match.group(3),
        min_grade=grade,
        outcome=outcome,
    )


def tokenize(text: str) -> list:
    """Разложить выражение на атомы, скобки и связки."""
    text = normalize(text)
    tokens: list = []
    position = 0
    while position < len(text):
        if text[position] == " ":
            position += 1
            continue
        for keyword in ("AND", "OR"):
            if text.startswith(keyword, position) and not text[position + len(keyword):position + len(keyword) + 1].isalnum():
                tokens.append(keyword)
                position += len(keyword)
                break
        else:
            atom, end = _atom_at(text, position)
            if atom is not None:
                tokens.append(atom)
                position = end
            elif text[position] in "()":
                tokens.append(text[position])
                position += 1
            else:
                # неразобранный хвост пропускаем, чтобы не терять остальное выражение
                position += 1
    return tokens


def parse_expression(text: str):
    """Разобрать текст требования в дерево условий."""
    tokens = tokenize(text)
    if not tokens:
        return None
    node, index = _parse_any(tokens, 0)
    return node if index >= 0 else None


def _parse_any(tokens: list, index: int):
    node, index = _parse_all(tokens, index)
    terms = [node] if node is not None else []
    while index < len(tokens) and tokens[index] == "OR":
        right, index = _parse_all(tokens, index + 1)
        if right is not None:
            terms.append(right)
    if not terms:
        return None, index
    return (terms[0] if len(terms) == 1 else Any(tuple(terms))), index


def _parse_all(tokens: list, index: int):
    node, index = _parse_atom(tokens, index)
    terms = [node] if node is not None else []
    while index < len(tokens) and tokens[index] == "AND":
        right, index = _parse_atom(tokens, index + 1)
        if right is not None:
            terms.append(right)
    if not terms:
        return None, index
    return (terms[0] if len(terms) == 1 else All(tuple(terms))), index


def _parse_atom(tokens: list, index: int):
    if index >= len(tokens):
        return None, index
    token = tokens[index]
    if token == "(":
        node, index = _parse_any(tokens, index + 1)
        if index < len(tokens) and tokens[index] == ")":
            index += 1
        return node, index
    if token in (")", "AND", "OR"):
        return None, index
    return token, index + 1


def parse_audiences(cell: str) -> tuple[list[Audience], bool]:
    """Разобрать колонку приоритета: список аудиторий и флаг разрешения преподавателя."""
    text = normalize(cell)
    if not text:
        return [], False
    if PERMISSION.search(text):
        return [], True

    audiences: list[Audience] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        match = AUDIENCE.match(part)
        if not match:
            audiences.append(Audience(raw=part))
            continue
        year, school, program, pending = match.groups()
        audiences.append(
            Audience(
                year=int(year) if year else None,
                school=school,
                program=program or None,
                pending_graduation=bool(pending),
                raw=part,
            )
        )
    return audiences, False


def is_section_header(row: list) -> bool:
    """Строка-разделитель: название школы или департамента в единственной ячейке."""
    filled = [c for c in row if normalize(c)]
    return len(filled) == 1 and bool(normalize(row[0]))


def _number(value: str, cast):
    value = normalize(value)
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def parse_row(row: list, term: str, school: str, department: str) -> CourseOffering | None:
    """Разобрать строку таблицы в CourseOffering."""
    code = normalize(row[1]) if len(row) > 1 else ""
    if not code:
        return None

    priorities: list[list[Audience]] = []
    permission = False
    for column in range(8, 12):
        audiences, flag = parse_audiences(row[column] if len(row) > column else "")
        permission = permission or flag
        priorities.append(audiences)

    while priorities and not priorities[-1]:
        priorities.pop()

    return CourseOffering(
        term=term,
        school=school,
        department=department,
        code=code,
        title=normalize(row[2]) if len(row) > 2 else "",
        credits_us=_number(row[3], float) if len(row) > 3 else None,
        credits_ects=_number(row[4], int) if len(row) > 4 else None,
        prerequisite=parse_expression(row[5]) if len(row) > 5 else None,
        corequisite=parse_expression(row[6]) if len(row) > 6 else None,
        antirequisite=parse_expression(row[7]) if len(row) > 7 else None,
        priorities=priorities,
        instructor_permission=permission,
    )


def parse_pdf(path: Path, term: str | None = None) -> list[CourseOffering]:
    """Разобрать весь документ требований и приоритетов."""
    import pdfplumber

    offerings: list[CourseOffering] = []
    school = department = ""
    with pdfplumber.open(path) as pdf:
        if term is None:
            first = pdf.pages[0].extract_text() or ""
            match = re.search(r"(Fall|Spring|Summer)\s+(\d{4})", first)
            term = f"{match.group(1)} {match.group(2)}" if match else path.stem

        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row or normalize(row[0]) == "#":
                    continue
                if is_section_header(row):
                    name = normalize(row[0])
                    # Школа идёт отдельной строкой перед своими департаментами.
                    if name.upper() in SCHOOLS:
                        school = name
                    else:
                        department = name
                    continue
                offering = parse_row(row, term, school, department)
                if offering is not None:
                    offerings.append(offering)
    return offerings


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Разобрать требования и приоритеты регистрации")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    offerings = parse_pdf(args.pdf)
    term = offerings[0].term if offerings else "?"
    with_prereq = sum(1 for o in offerings if o.prerequisite)
    print(f"{term}: курсов {len(offerings)}, с пререквизитами {with_prereq}")

    if args.output:
        payload = [
            {
                "term": o.term,
                "school": o.school,
                "department": o.department,
                "code": o.code,
                "title": o.title,
                "credits_ects": o.credits_ects,
                "prerequisite": str(o.prerequisite) if o.prerequisite else None,
                "corequisite": str(o.corequisite) if o.corequisite else None,
                "antirequisite": str(o.antirequisite) if o.antirequisite else None,
                "prerequisite_codes": sorted(course_codes(o.prerequisite)),
                "priorities": [[a.raw for a in tier] for tier in o.priorities],
                "instructor_permission": o.instructor_permission,
            }
            for o in offerings
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {args.output}")


if __name__ == "__main__":
    main()
