"""Разбор отчётов о распределении оценок.

Institutional Research публикует их по школам и семестрам, и это единственный
источник, где написано, чем курс заканчивается для тех, кто его взял: средний
балл, медиана, разброс и доли оценок вплоть до отсева. Handbook говорит, какая
оценка нужна, чтобы курс засчитали; расписание — сколько человек записалось;
и только отсюда видно, чем дело кончилось.

Курс здесь разложен по секциям, но имени преподавателя в отчёте нет — есть
только номер секции. Имя берётся из расписания того же семестра, по паре
"код курса + номер секции". Это важно: разброс среднего балла между секциями
одного курса больше, чем между уровнями курсов, то есть кто ведёт, влияет
сильнее, чем что ведут.

    uv run python -m course_recommender.data.grades UG_Grade_Report_*.pdf \\
      --schedule school_schedule_by_term*.pdf
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

NUMBER = r"[\d.]+"
# CSCI 151 Programming for Scientists 2 130 2.48 1.42 3.0 33.8 ... 1.5 133
ROW = re.compile(
    rf"^([A-Z]{{2,5}}\s\d{{3}}[A-Za-z]?)\s+(.+?)\s+(\d{{1,2}})\s+(\d+)\s+({NUMBER})\s+({NUMBER})"
    rf"\s+({NUMBER})((?:\s+{NUMBER}){{9}})\s+(\d+)$"
)
TERM = re.compile(r"\b(Fall|Spring|Summer)\s+(\d{4})\b")
DEPARTMENT = re.compile(r"^E\d+\.\s*(.+)$")
HEADER = "Course Title"
# Колонки долей идут в этом порядке и означают процент от всех выставленных оценок.
SHARES = ("A", "B", "C", "D", "F", "P", "I", "AU", "W")


@dataclass(frozen=True)
class SectionGrades:
    """Чем закончилась одна секция курса."""

    term: str
    school: str
    department: str
    code: str
    title: str
    section: int
    graded: int  # сколько оценок пошло в GPA
    average: float
    deviation: float
    median: float
    shares: dict[str, float] = field(default_factory=dict)
    letters: int = 0
    instructors: tuple[str, ...] = ()

    @property
    def withdrew(self) -> float:
        """Доля забравших документы с курса."""
        return self.shares.get("W", 0.0)

    @property
    def failed(self) -> float:
        return self.shares.get("F", 0.0)

    @property
    def risky(self) -> float:
        """Доля тех, для кого курс кончился плохо: F, D или уход."""
        return self.failed + self.shares.get("D", 0.0) + self.withdrew


@dataclass
class CourseGrades:
    """Свод по курсу за все известные семестры."""

    code: str
    title: str = ""
    sections: list[SectionGrades] = field(default_factory=list)

    @property
    def graded(self) -> int:
        return sum(section.graded for section in self.sections)

    @property
    def average(self) -> float | None:
        """Средний балл по курсу, взвешенный по числу оценок."""
        if not self.graded:
            return None
        return sum(s.average * s.graded for s in self.sections) / self.graded

    @property
    def risky(self) -> float | None:
        """Доля плохих исходов, взвешенная по числу оценок."""
        if not self.graded:
            return None
        return sum(s.risky * s.graded for s in self.sections) / self.graded

    @property
    def terms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(section.term for section in self.sections))

    def spread(self, term: str | None = None) -> float | None:
        """Разброс среднего балла между секциями одного семестра.

        Секции читают разные преподаватели по одной программе, поэтому
        разброс здесь — это про то, кто ведёт, а не про то, что ведут.
        """
        best: float | None = None
        for name in ([term] if term else self.terms):
            values = [s.average for s in self.sections if s.term == name and s.graded]
            if len(values) > 1:
                width = max(values) - min(values)
                best = width if best is None else max(best, width)
        return best

    def by_instructor(self) -> dict[str, list[SectionGrades]]:
        """Секции, разложенные по преподавателям."""
        grouped: dict[str, list[SectionGrades]] = {}
        for section in self.sections:
            for name in section.instructors:
                grouped.setdefault(name, []).append(section)
        return grouped


def parse_row(line: str, term: str, school: str, department: str) -> SectionGrades | None:
    """Разобрать строку отчёта.

    Строки без выставленных оценок пропускаются: у них нет ни среднего, ни
    медианы, и в статистике им делать нечего.
    """
    match = ROW.match(line.strip())
    if not match:
        return None
    values = [float(value) for value in match.group(8).split()]
    return SectionGrades(
        term=term,
        school=school,
        department=department,
        code=match.group(1),
        title=match.group(2).strip(),
        section=int(match.group(3)),
        graded=int(match.group(4)),
        average=float(match.group(5)),
        deviation=float(match.group(6)),
        median=float(match.group(7)),
        shares=dict(zip(SHARES, values)),
        letters=int(match.group(9)),
    )


def parse_text(text: str, term: str = "", school: str = "") -> list[SectionGrades]:
    """Разобрать текст отчёта: только детальные таблицы по курсам."""
    rows: list[SectionGrades] = []
    department = ""
    in_table = False

    for line in text.split("\n"):
        stripped = line.strip()
        if HEADER in stripped:
            in_table = True
            continue
        heading = DEPARTMENT.match(stripped)
        if heading:
            department = heading.group(1).strip()
            continue
        if not in_table:
            continue
        row = parse_row(stripped, term, school, department)
        if row is not None:
            rows.append(row)
    return rows


def parse_pdf(path: Path) -> list[SectionGrades]:
    """Разобрать отчёт целиком. Семестр и школа берутся с обложки."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]

    cover = pages[0] if pages else ""
    term_match = TERM.search(cover)
    term = f"{term_match.group(1)} {term_match.group(2)}" if term_match else path.stem
    lines = [line.strip() for line in cover.split("\n") if line.strip()]
    school = next((line for line in lines if line.lower().startswith("school") or "business" in line.lower()), "")

    rows: list[SectionGrades] = []
    for text in pages:
        if HEADER in text:
            rows.extend(parse_text(text, term, school))
    return rows


def instructors_from(snapshots, kinds: tuple[str, ...] = ("L",)) -> dict[tuple[str, str, int], tuple[str, ...]]:
    """Кто вёл: из расписания, по паре "курс + номер секции" внутри семестра.

    Считаем по лекциям: у секции 1 есть ещё лаборатория 1Lb и рецитация 1R,
    и ведут их обычно другие люди. Оценку ставит лектор, поэтому смешивать
    их в один список значит приписать ассистенту чужой результат. Если лекций
    у курса нет вовсе, берём что есть.
    """
    found: dict[tuple[str, str, int], set[str]] = {}
    fallback: dict[tuple[str, str, int], set[str]] = {}
    for snapshot in snapshots:
        for section in snapshot.sections:
            if section.number is None or not section.faculty:
                continue
            key = (snapshot.term, section.code, section.number)
            target = found if section.kind in kinds else fallback
            target.setdefault(key, set()).update(section.faculty)
    merged = {**{k: v for k, v in fallback.items() if k not in found}, **found}
    return {key: tuple(sorted(names)) for key, names in merged.items()}


def attach_instructors(rows: list[SectionGrades], snapshots) -> list[SectionGrades]:
    """Проставить преподавателей из расписания.

    В отчёте об оценках имён нет — есть номер секции. Расписание того же
    семестра знает и номер, и преподавателя, и это единственный способ
    связать оценку с тем, кто её ставил.
    """
    from dataclasses import replace

    known = instructors_from(snapshots)
    return [
        replace(row, instructors=known.get((row.term, row.code, row.section), row.instructors))
        for row in rows
    ]


def by_course(rows: list[SectionGrades]) -> dict[str, CourseGrades]:
    """Свести строки по курсам."""
    courses: dict[str, CourseGrades] = {}
    for row in rows:
        course = courses.setdefault(row.code, CourseGrades(code=row.code, title=row.title))
        course.title = course.title or row.title
        course.sections.append(row)
    return courses


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Разобрать отчёты о распределении оценок")
    parser.add_argument("report", type=Path, nargs="+", help="PDF UG_Grade_Report_*")
    parser.add_argument("--schedule", type=Path, nargs="*", default=[],
                        help="PDF расписаний — чтобы узнать преподавателей")
    parser.add_argument("--course", help="показать один курс подробно")
    args = parser.parse_args()

    rows: list[SectionGrades] = []
    seen: set[tuple[str, str, str, int]] = set()
    for path in args.report:
        for row in parse_pdf(path):
            key = (row.term, row.school, row.code, row.section)
            # Один и тот же отчёт мог быть скачан дважды.
            if key not in seen:
                seen.add(key)
                rows.append(row)

    if args.schedule:
        from .schedule import parse_pdf as parse_schedule

        snapshots = [parse_schedule(path).filter_level("UG") for path in args.schedule]
        rows = attach_instructors(rows, snapshots)

    courses = by_course(rows)
    named = sum(1 for row in rows if row.instructors)
    terms = sorted({row.term for row in rows})
    print(f"семестров: {len(terms)} ({', '.join(terms)})")
    print(f"секций: {len(rows)}, курсов: {len(courses)}, с преподавателем: {named}")

    if not args.course:
        spread = [(c.spread(), c.code) for c in courses.values() if c.spread()]
        spread.sort(reverse=True)
        print("\nгде секции расходятся сильнее всего:")
        for width, code in spread[:8]:
            print(f"   {code:10s} разброс {width:.2f} балла  {courses[code].title[:44]}")
        return

    course = next((c for code, c in courses.items() if args.course.upper() in code), None)
    if course is None:
        parser.error(f"курс не найден: {args.course}")
    print(f"\n{course.code} {course.title}")
    print(f"средний балл {course.average:.2f}, плохих исходов {course.risky:.0f}%")
    for section in sorted(course.sections, key=lambda s: (s.term, s.section)):
        who = ", ".join(section.instructors) or "—"
        print(
            f"   {section.term:12s} секция {section.section}  балл {section.average:.2f}  "
            f"медиана {section.median:.2f}  n={section.graded:3d}  ушли {section.withdrew:4.1f}%  {who[:40]}"
        )


if __name__ == "__main__":
    main()
