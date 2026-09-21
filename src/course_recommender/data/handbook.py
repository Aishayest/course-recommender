"""Разбор handbook: учебные планы по специальностям и семестрам.

Основа handbook — таблицы вида

    Fall | minimum required grade | ECTS | Spring | minimum required grade | ECTS

то есть рекомендуемый план на каждый год обучения, с минимальной проходной
оценкой по каждому курсу. Их ~59 в каждом выпуске handbook, формат одинаков
для всех годов поступления.

Связь "таблица -> специальность -> год обучения" восстанавливается по
геометрии блоков: порядок элементов в JSON произвольный, поэтому берём
ближайший заголовок выше таблицы.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..domain import GRADE_POINTS
from .canva import Block, Page, Table

# Кириллические двойники латиницы: в оценках встречается "С-" с кириллической С.
HOMOGLYPHS = str.maketrans("АВЕКМНОРСТУХаеорсух", "ABEKMHOPCTYXaeopcyx")

COURSE_CODE = re.compile(r"\b([A-Z]{2,5})\s*(\d{3}[A-Z]?)\b")
GRADE = re.compile(r"^([A-D][+-]?|F)\s*(\**)$")
YEAR_LABEL = re.compile(r"^YEAR\s*(\d)$", re.IGNORECASE)
PROGRAM_HEADING = re.compile(r"^(BA|BS|BSc|BEng|BBA)\s+(?:in|of)\s+(.+)$", re.IGNORECASE)
TOTAL_ROW = re.compile(r"total\s+semester", re.IGNORECASE)
FOOTNOTE_LINE = re.compile(r"^(\*+)\s*(.+)$")
# "or" как разделитель альтернатив — только вне скобок
ALTERNATIVE = re.compile(r"\s+or\s+", re.IGNORECASE)
CONTINUATION = re.compile(r"^or\s+", re.IGNORECASE)
TRAILING_MARKER = re.compile(r"\*+$")


def normalize(text: str) -> str:
    """Починить гомоглифы и схлопнуть пробелы."""
    text = unicodedata.normalize("NFKC", text).translate(HOMOGLYPHS)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class CourseRef:
    """Ссылка на курс в плане.

    У части позиций кода нет: "Kazakh Language", "General Elective" —
    это категория, а не конкретный курс.
    """

    code: str | None
    title: str

    @property
    def is_placeholder(self) -> bool:
        return self.code is None


@dataclass
class PlanEntry:
    """Одна позиция учебного плана."""

    admission_year: int
    program: str
    degree: str
    study_year: int
    term: str  # "fall" | "spring"
    options: list[CourseRef]  # несколько — если в ячейке "A or B"
    min_grade: str | None = None
    credits: tuple[int, ...] = ()
    footnotes: list[str] = field(default_factory=list)

    @property
    def min_grade_points(self) -> float | None:
        return GRADE_POINTS.get(self.min_grade) if self.min_grade else None

    @property
    def is_choice(self) -> bool:
        return len(self.options) > 1


def parse_grade(cell: str) -> tuple[str | None, str]:
    """Оценка и маркер сноски: "C-**" -> ("C-", "**")."""
    match = GRADE.match(normalize(cell))
    return (match.group(1), match.group(2)) if match else (None, "")


def parse_credits(cell: str) -> tuple[int, ...]:
    """Кредиты: "6" -> (6,), "6 or 8" -> (6, 8)."""
    return tuple(int(n) for n in re.findall(r"\d+", normalize(cell)))


def split_alternatives(text: str) -> list[str]:
    """Разбить по "or", не трогая содержимое скобок.

    "CSCI course (e.g. CSCI 115 or CSCI 151)" — одна позиция,
    "Major Elective 3 (BIOL 456) or Honors Thesis (BIOL 490)" — две.
    """
    parts: list[str] = []
    depth = start = index = 0
    while index < len(text):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            match = ALTERNATIVE.match(text, index)
            if match:
                parts.append(text[start : match.start()])
                start = index = match.end()
                continue
        index += 1
    parts.append(text[start:])
    return [p for p in parts if p.strip()]


def is_continuation(cell: str) -> bool:
    """Ячейка — продолжение предыдущей строки: "or HST 100 History...".

    В Canva объединённые по вертикали варианты выбора разнесены по строкам,
    и кредиты указаны только в первой из них.
    """
    return bool(CONTINUATION.match(normalize(cell)))


def parse_course_cell(cell: str) -> list[CourseRef]:
    """Разобрать ячейку курса, включая альтернативы через "or"."""
    text = CONTINUATION.sub("", normalize(cell))
    if not text or TOTAL_ROW.search(text):
        return []

    refs: list[CourseRef] = []
    for part in split_alternatives(text):
        part = TRAILING_MARKER.sub("", part.strip(" :;,")).strip(" :;,")
        if not part:
            continue
        match = COURSE_CODE.search(part)
        if match:
            code = f"{match.group(1)} {match.group(2)}"
            title = part[match.end() :].strip(" :;,-")
            refs.append(CourseRef(code=code, title=title))
        else:
            refs.append(CourseRef(code=None, title=part))
    return refs


def parse_program_heading(text: str) -> tuple[str, str] | None:
    """"BSc in  Computer Science" -> ("BSc", "COMPUTER SCIENCE")."""
    match = PROGRAM_HEADING.match(normalize(text))
    if not match:
        return None
    degree = match.group(1)
    degree = {"BS": "BSc"}.get(degree, degree)
    return degree, match.group(2).upper().strip()


def _term_at(header: list[str], offset: int) -> str | None:
    """Семестр, если с этой колонки начинается блок плана."""
    if len(header) < offset + 3:
        return None
    label = header[offset]
    if not label.startswith(("fall", "spring")):
        return None
    if not header[offset + 1].startswith("minimum") or "ects" not in header[offset + 2]:
        return None
    return "fall" if label.startswith("fall") else "spring"


def plan_terms(table: Table) -> list[tuple[str, int]]:
    """Семестры таблицы и смещение их колонок.

    Обычно план идёт одной таблицей на шесть колонок (осень и весна рядом),
    но кое-где семестры разнесены по отдельным таблицам на три колонки.
    """
    header = [normalize(c).lower() for c in table.header]
    terms = [(term, offset) for offset in (0, 3) if (term := _term_at(header, offset))]
    return terms


def is_plan_table(table: Table) -> bool:
    """Таблица учебного плана, а не календаря или списка курсов."""
    return bool(plan_terms(table))


def _page_footnotes(page: Page) -> dict[str, str]:
    """Сноски страницы по маркеру: "*" -> текст."""
    notes: dict[str, str] = {}
    for block in page.blocks:
        if block.kind != "text" or not block.text.lstrip().startswith("*"):
            continue
        for line in block.text.splitlines():
            match = FOOTNOTE_LINE.match(line.strip())
            if match:
                notes.setdefault(match.group(1), normalize(match.group(2)))
    return notes


def _nearest_year_above(page: Page, table: Block) -> int | None:
    """Заголовок "YEAR N", относящийся к таблице.

    Планы на странице разложены сеткой 2x2, и подписи стоят парами на одной
    высоте. Поэтому мало взять ближайшую сверху: сначала отбираем подписи,
    попадающие в горизонтальные границы таблицы, и только среди них берём
    ближайшую. Если перекрытия нет — откатываемся на ближайшую по расстоянию.
    """
    overlapping: list[tuple[float, int]] = []
    fallback: list[tuple[float, float, int]] = []

    for block in page.blocks:
        if block.kind != "text" or block.top >= table.top:
            continue
        match = YEAR_LABEL.match(normalize(block.text))
        if not match:
            continue
        year = int(match.group(1))
        gap = table.top - block.top
        if table.left <= block.center_x <= table.right:
            overlapping.append((gap, year))
        else:
            fallback.append((gap, abs(block.center_x - table.center_x), year))

    if overlapping:
        return min(overlapping)[1]
    if fallback:
        return min(fallback, key=lambda item: (item[0], item[1]))[2]
    return None


def parse_plans(pages: list[Page], admission_year: int) -> list[PlanEntry]:
    """Собрать все позиции учебных планов из handbook."""
    entries: list[PlanEntry] = []
    program: str | None = None
    degree: str = ""

    for page in pages:
        footnotes = _page_footnotes(page)
        for block in page.blocks:
            if block.kind == "text":
                heading = parse_program_heading(block.text)
                if heading:
                    degree, program = heading
                continue

            table = block.table
            if table is None or not is_plan_table(table) or program is None:
                continue

            study_year = _nearest_year_above(page, block)
            if study_year is None:
                continue

            terms = plan_terms(table)
            last: dict[str, PlanEntry] = {}
            for row in table.body:
                for term, offset in terms:
                    if len(row) < offset + 3:
                        continue
                    options = parse_course_cell(row[offset])
                    if not options:
                        continue

                    previous = last.get(term)
                    if is_continuation(row[offset]) and previous is not None:
                        previous.options.extend(options)
                        continue

                    grade, marker = parse_grade(row[offset + 1])
                    entry = PlanEntry(
                        admission_year=admission_year,
                        program=program,
                        degree=degree,
                        study_year=study_year,
                        term=term,
                        options=options,
                        min_grade=grade,
                        credits=parse_credits(row[offset + 2]),
                        footnotes=[footnotes[marker]] if marker in footnotes else [],
                    )
                    entries.append(entry)
                    last[term] = entry
    return entries
