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
from .electives import (
    ElectiveGroup,
    groups_from_requirements,
    kind_of_row,
    merge,
    parse_electives,
    slot_kind,
)
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
    # Тип электива, если это позиция на выбор: "Technical Elective 2" ->
    # technical. Списки у типов разные, и у каждой специальности свои.
    kind: str | None = None
    # Чем эту позицию можно закрыть. Пусто, пока не известен каталог курсов:
    # правило "любой курс CS 200+" без каталога не разворачивается.
    eligible_codes: frozenset[str] = frozenset()


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
    # Списки элективов специальности по типам: technical, natural science,
    # major. Это и есть то, чем отличаются свободные позиции плана у CS
    # и у математиков при одинаковом названии "Technical Elective".
    electives: dict[str, ElectiveGroup] = field(default_factory=dict)

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
                    kind=slot_kind(option.title),
                )
            )
    return slots


def build_requirements(rows: list[RequirementRow]) -> list[Requirement]:
    """Требования по категориям, с пометкой типа электива там, где он есть."""
    requirements = []
    for row in rows:
        if row.is_total or not row.credits:
            continue
        kind = row.kind
        requirements.append(
            Requirement(
                kind=kind,
                required_credits=row.credits,
                elective_kind=kind_of_row(row) if kind is CourseKind.ELECTIVE else None,
            )
        )
    return requirements


def build_program(
    entries: list[PlanEntry],
    rows: list[RequirementRow],
    admission_year: int,
    name: str,
    shared_kinds: dict[str, CourseKind] | None = None,
    electives: dict[str, ElectiveGroup] | None = None,
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
        requirements=build_requirements(rows),
        slots=build_slots(entries),
        total_credits=degree_credits(rows),
        min_major_grade=grades[0] if grades else None,
        electives=dict(electives or {}),
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

    names = set(plans) | set(requirements)
    groups = merge(
        parse_electives(pages, admission_year, names),
        groups_from_requirements(all_rows, admission_year),
    )

    return {
        name: build_program(
            plans.get(name, []),
            requirements.get(name, []),
            admission_year,
            name,
            shared,
            electives_of(groups, name),
        )
        for name in names
    }


def electives_of(
    groups: dict[tuple[str, str], ElectiveGroup], program: str
) -> dict[str, ElectiveGroup]:
    """Списки элективов одной специальности, дополненные общеуниверситетскими.

    Свой список всегда важнее: технический электив у CS и у робототехники
    называется одинаково, а состоит из разного. Общеуниверситетская страница
    добавляется только там, где у специальности своего списка нет — так
    устроены социальные и гуманитарные элективы, они на всех одни.
    """
    own = {kind: group for (name, kind), group in groups.items() if name == program}
    for (name, kind), group in groups.items():
        if not name:
            own.setdefault(kind, group)
    return own


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


def attach_electives(
    programs: dict[str, Program],
    catalog: dict[str, str],
    schools: dict[str, str] | None = None,
    credits: dict[str, int] | None = None,
) -> int:
    """Развернуть слоты плана в конкретные курсы по спискам элективов.

    До этого момента "Technical Elective" — только название позиции. Каталог
    превращает его в набор кодов: часть handbook назвал поимённо, часть задана
    правилом, которое без каталога не разворачивается вовсе.

    Курсы, уже стоящие в плане обязательными, из списка вычитаются: закрыть
    ими свободную позицию нельзя, они и так обязательны.
    """
    filled = 0
    for program in programs.values():
        required = frozenset(program.courses)
        resolved = {
            kind: group.resolve(catalog, required, schools) - required
            for kind, group in program.electives.items()
        }
        program.slots = [
            replace(slot, eligible_codes=frozenset(resolved.get(slot.kind, ())))
            for slot in program.slots
        ]
        program.requirements = [
            replace(requirement, eligible_codes=frozenset(resolved[requirement.elective_kind]))
            if requirement.elective_kind in resolved
            else requirement
            for requirement in program.requirements
        ]

        # Курсы, которыми закрываются свободные позиции, попадают в каталог
        # специальности: без этого их некому предложить — в плане они не стоят.
        # Только те, что в каталоге действительно есть: handbook перечисляет
        # и курсы, которые в этом семестре не читают, и предлагать их нельзя.
        for kind, codes in resolved.items():
            for code in sorted(codes & set(catalog)):
                if code in program.courses:
                    continue
                program.courses[code] = Course(
                    code=code,
                    title=catalog.get(code, ""),
                    credits=(credits or {}).get(code, 0),
                    kind=CourseKind.ELECTIVE,
                    elective_kind=kind,
                )
                filled += 1
    return filled


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
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Показать собранную специальность")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--program", help="часть названия, без учёта регистра")
    parser.add_argument(
        "--catalog", type=Path, help="PDF Course Requirements — раскрыть списки элективов"
    )
    args = parser.parse_args()

    programs = load_programs(args.year)
    if args.catalog:
        from .registration import parse_pdf

        offerings = parse_pdf(args.catalog)
        attach_electives(
            programs,
            {o.code: o.title for o in offerings},
            {o.code: o.school for o in offerings},
            {o.code: o.credits_ects or 0 for o in offerings},
        )

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
    on_plan = sum(1 for c in program.courses.values() if c.recommended_semester is not None)
    print(
        f"курсов в плане: {on_plan}, слотов на выбор: {len(program.slots)}, "
        f"кандидатов в элективы: {len(program.courses) - on_plan}"
    )
    for kind, group in sorted(program.electives.items()):
        from .electives import describe

        print(f"элективы «{kind}»: {describe(group)}")

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
            choice = f"  ({len(slot.eligible_codes)} вариантов)" if slot.eligible_codes else ""
            print(f"  {'—':10s} {slot.credits or 0:2d} ECTS  {slot.min_grade or '—':3s}  "
                  f"{'слот':11s} {slot.name[:40]}{choice}")


if __name__ == "__main__":
    main()
