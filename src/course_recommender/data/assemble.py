"""Сборка доменных объектов из разобранного handbook.

Парсеры дают сырые строки: PlanEntry — позиции учебного плана, RequirementRow —
требования по категориям. Здесь они сводятся в Program: каталог курсов,
требования и слоты плана для конкретной связки "год поступления + специальность".

Год поступления — обязательная часть ключа: у каждого потока свой handbook,
и советовать студенту правила чужого года нельзя.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

from ..conditions import All
from ..domain import Course, CourseKind, Requirement
from .canva import Page
from .handbook import PlanEntry, parse_plans
from .requirements import RequirementRow, degree_credits, parse_requirements

TERM_OFFSET = {"fall": 1, "spring": 2}
# Осенние курсы читаются в нечётных семестрах, весенние — в чётных.
TERM_SEMESTERS = {"fall": (1, 3, 5, 7), "spring": (2, 4, 6, 8)}


@dataclass(frozen=True)
class PlanSlot:
    """Позиция плана без конкретного курса.

    "Kazakh Language", "General Elective", "Technical Elective 2" — это
    категория, которую студент закрывает на выбор, а не отдельный курс.
    """

    name: str
    semester: int
    term: str
    credits: int | None
    min_grade: str | None = None


@dataclass
class Program:
    """Специальность одного года поступления."""

    admission_year: int
    name: str
    degree: str
    courses: dict[str, Course] = field(default_factory=dict)
    requirements: list[Requirement] = field(default_factory=list)
    slots: list[PlanSlot] = field(default_factory=list)
    total_credits: int | None = None
    min_major_grade: str | None = None

    @property
    def catalog(self) -> list[Course]:
        return list(self.courses.values())

    def semester_courses(self, semester: int) -> list[Course]:
        """Курсы, стоящие в плане на этот семестр."""
        return [c for c in self.courses.values() if c.recommended_semester == semester]


def semester_index(study_year: int, term: str) -> int:
    """Номер семестра сквозной нумерацией: 2-й курс, весна -> 4."""
    return (study_year - 1) * 2 + TERM_OFFSET[term]


def dominant_subject(entries: list[PlanEntry]) -> str | None:
    """Профильный префикс специальности: у CS это CSCI, у физиков PHYS.

    Берём самый частый префикс среди курсов плана 3-4 курса: на старших
    курсах общеуниверситетские дисциплины уже закончились.
    """
    prefixes = Counter(
        option.code.split()[0]
        for entry in entries
        if entry.study_year >= 3
        for option in entry.options
        if option.code
    )
    return prefixes.most_common(1)[0][0] if prefixes else None


def _kinds_from_requirements(rows: list[RequirementRow]) -> dict[str, CourseKind]:
    """Категории курсов, явно перечисленных в таблицах требований."""
    kinds: dict[str, CourseKind] = {}
    for row in rows:
        if row.is_total:
            continue
        for ref in row.courses:
            if ref.code:
                kinds.setdefault(ref.code, row.kind)
    return kinds


def resolve_kind(
    code: str,
    own_kinds: dict[str, CourseKind],
    shared_kinds: dict[str, CourseKind],
    subject: str | None,
) -> CourseKind:
    """Категория курса по убыванию надёжности источника.

    1. Таблица требований самой специальности — прямое указание handbook.
    2. Профильный префикс: для CS курс CSCI профильный, чем бы он ни был
       у других специальностей (там же CSCI идёт как общеуниверситетский).
    3. Core-карта, собранная по другим программам.
    """
    if code in own_kinds:
        return own_kinds[code]
    if subject and code.startswith(f"{subject} "):
        return CourseKind.MAJOR
    return shared_kinds.get(code, CourseKind.UNSPECIFIED)


def build_courses(
    entries: list[PlanEntry],
    own_kinds: dict[str, CourseKind],
    shared_kinds: dict[str, CourseKind],
    subject: str | None,
) -> dict[str, Course]:
    """Каталог курсов специальности из позиций плана.

    Категория, которую не удалось определить, остаётся UNSPECIFIED: приписать
    её наугад нельзя, иначе подсчёт недостающих кредитов будет врать.
    """
    courses: dict[str, Course] = {}
    for entry in entries:
        semester = semester_index(entry.study_year, entry.term)
        for option in entry.options:
            if not option.code:
                continue
            kind = resolve_kind(option.code, own_kinds, shared_kinds, subject)
            existing = courses.get(option.code)
            # Курс может встретиться в плане дважды — оставляем первое вхождение,
            # оно и есть рекомендованный семестр.
            if existing is not None and existing.recommended_semester <= semester:
                continue
            courses[option.code] = Course(
                code=option.code,
                title=option.title or (existing.title if existing else ""),
                credits=entry.credits[0] if entry.credits else 0,
                kind=kind,
                semesters_offered=TERM_SEMESTERS[entry.term],
                min_grade=entry.min_grade,
                recommended_semester=semester,
            )
    return courses


def build_slots(entries: list[PlanEntry]) -> list[PlanSlot]:
    """Позиции плана без кода курса — категории на выбор."""
    slots: list[PlanSlot] = []
    for entry in entries:
        for option in entry.options:
            if option.code:
                continue
            slots.append(
                PlanSlot(
                    name=option.title,
                    semester=semester_index(entry.study_year, entry.term),
                    term=entry.term,
                    credits=entry.credits[0] if entry.credits else None,
                    min_grade=entry.min_grade,
                )
            )
    return slots


def build_program(
    entries: list[PlanEntry],
    rows: list[RequirementRow],
    admission_year: int,
    name: str,
    shared_kinds: dict[str, CourseKind] | None = None,
    ) -> Program:
    """Собрать специальность из позиций плана и строк требований.

    Своя таблица требований важнее общей: ECON 101 для экономистов профильный,
    а для остальных — общеуниверситетский курс по бизнесу.
    """
    own_kinds = _kinds_from_requirements(rows)
    subject = dominant_subject(entries)
    grades = [row.min_grade for row in rows if row.min_grade]
    return Program(
        admission_year=admission_year,
        name=name,
        degree=entries[0].degree if entries else "",
        courses=build_courses(entries, own_kinds, shared_kinds or {}, subject),
        requirements=[
            Requirement(kind=row.kind, required_credits=row.credits)
            for row in rows
            if not row.is_total and row.credits
        ],
        slots=build_slots(entries),
        total_credits=degree_credits(rows),
        min_major_grade=grades[0] if grades else None,
    )


def core_kinds(rows: list[RequirementRow]) -> dict[str, CourseKind]:
    """Общеуниверситетские категории, собранные по всем специальностям.

    Таблицы требований есть не у всех программ, но секция core у них общая:
    HST 100, KAZ, Ethics, Writing одинаковы для всего университета. Поэтому
    категории из core-секции переносим на специальности, где своей таблицы нет.
    """
    kinds: dict[str, CourseKind] = {}
    for row in rows:
        # Только настоящие core-строки: элективы у каждой специальности свои,
        # и перенос их на чужую программу приписал бы курсу не ту категорию.
        if row.section != "core" or row.is_total or row.kind is not CourseKind.CORE:
            continue
        for ref in row.courses:
            if ref.code:
                kinds.setdefault(ref.code, row.kind)
    return kinds


def build_programs(
    pages: list[Page], admission_year: int, shared_kinds: dict[str, CourseKind] | None = None
) -> dict[str, Program]:
    """Все специальности одного выпуска handbook.

    shared_kinds позволяет передать core-категории, собранные по всем годам:
    в некоторых выпусках core-требования записаны одними названиями, без кодов
    курсов, а состав общеуниверситетского блока от года к году почти не меняется.
    """
    plans: dict[str, list[PlanEntry]] = {}
    for entry in parse_plans(pages, admission_year):
        plans.setdefault(entry.program, []).append(entry)

    all_rows = parse_requirements(pages, admission_year)
    shared = {**core_kinds(all_rows), **(shared_kinds or {})}
    requirements: dict[str, list[RequirementRow]] = {}
    for row in all_rows:
        requirements.setdefault(row.program, []).append(row)

    return {
        name: build_program(
            plans.get(name, []), requirements.get(name, []), admission_year, name, shared
        )
        for name in set(plans) | set(requirements)
    }


def attach_requirements(programs: dict[str, Program], offerings) -> int:
    """Проставить курсам настоящие условия допуска из документа регистрации.

    Курс, который в документе есть, но без пререквизитов, получает пустое
    условие All(()) — оно всегда истинно. Это не то же самое, что отсутствие
    данных: пустое условие означает "точно известно, что пререквизитов нет",
    и такому курсу подстраховка по позиции в плане уже не нужна.
    """
    by_code = {o.code: o for o in offerings}
    updated = 0
    for program in programs.values():
        for code, course in list(program.courses.items()):
            offering = by_code.get(code)
            if offering is None:
                continue
            program.courses[code] = replace(
                course, requirement=offering.prerequisite or All(())
            )
            updated += 1
    return updated


def shared_core_kinds() -> dict[str, CourseKind]:
    """Core-категории по всем выгруженным handbook.

    Ядро университетской программы стабильно между потоками, поэтому HST 100,
    опознанный как core в одном выпуске, остаётся core и в тех, где таблица
    требований перечисляет категории без кодов.
    """
    from ..config import HANDBOOK_SOURCES, handbook_path
    from .canva import load

    kinds: dict[str, CourseKind] = {}
    for year in HANDBOOK_SOURCES:
        path = handbook_path(year)
        if path.exists():
            kinds.update(core_kinds(parse_requirements(load(path), year)))
    return kinds


def load_programs(admission_year: int, cross_year_core: bool = True) -> dict[str, Program]:
    """Собрать специальности из выгруженного handbook."""
    from ..config import handbook_path
    from .canva import load

    shared = shared_core_kinds() if cross_year_core else None
    return build_programs(load(handbook_path(admission_year)), admission_year, shared)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Показать собранную специальность")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--program", help="часть названия, без учёта регистра")
    args = parser.parse_args()

    programs = load_programs(args.year)
    if not args.program:
        for name in sorted(programs):
            program = programs[name]
            print(f"{len(program.courses):3d} курсов  {len(program.requirements):2d} требований  {name}")
        return

    matches = [p for name, p in programs.items() if args.program.upper() in name]
    if not matches:
        parser.error(f"специальность не найдена: {args.program}")

    program = matches[0]
    print(f"{program.degree} in {program.name} ({program.admission_year})")
    print(f"кредитов на диплом: {program.total_credits or '—'}")
    print(f"минимальная оценка по профильным: {program.min_major_grade or '—'}")
    print(f"курсов в плане: {len(program.courses)}, слотов на выбор: {len(program.slots)}")

    for semester in range(1, 9):
        courses = sorted(program.semester_courses(semester), key=lambda c: c.code)
        slots = [s for s in program.slots if s.semester == semester]
        if not courses and not slots:
            continue
        year, term = (semester + 1) // 2, "осень" if semester % 2 else "весна"
        print(f"\n--- семестр {semester} ({year} курс, {term}) ---")
        for course in courses:
            print(f"  {course.code:10s} {course.credits:2d} ECTS  {course.min_grade or '—':3s}  "
                  f"{course.kind.value:11s} {course.title[:40]}")
        for slot in slots:
            print(f"  {'—':10s} {slot.credits or 0:2d} ECTS  {slot.min_grade or '—':3s}  "
                  f"{'слот':11s} {slot.name[:40]}")


if __name__ == "__main__":
    main()
