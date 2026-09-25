"""Сборка рекомендации: что брать в следующем семестре и на что реально попасть.

Здесь нет обученной модели, и это сознательно. Всё, что известно, —
детерминированные факты из документов университета: требования handbook,
пререквизиты, тиры приоритета и то, как курс заполнялся в прошлые семестры.
Их достаточно, чтобы отвечать на исходный вопрос, и они же задают эталон,
который обученная модель обязана побить, иначе она не нужна.

Оценка шанса попасть — эвристика, а не подгонка. Данных по конкретным
студентам нет: Enr и Cap описывают спрос на курс целиком, а не то, кому
досталось место. Поэтому шанс считается на уровне курса и тира приоритета,
и выдавать его за персональную вероятность было бы враньём.
"""

from __future__ import annotations

from dataclasses import dataclass

from .conditions import course_codes, evaluate
from .config import UTILITY_WEIGHTS
from .constraints import eligible_courses, remaining_requirements
from .domain import Course, CourseKind, Student

# Шанс получить место, ЕСЛИ курс заполнился. Эти числа подобраны, а не
# выведены: выгрузки показывают, сколько человек записалось, но не кто из них
# какого тира, и очередь по ним не восстанавливается ни одной моделью. Пока
# нет данных о том, кому досталось место, здесь останется предположение —
# и оно нарочно стоит отдельно от измеренного.
TIER_PLACE = {1: 0.85, 2: 0.60, 3: 0.35, 4: 0.15}
NO_TIER_PLACE = 0.05
# Курс без истории: ни да, ни нет.
UNKNOWN_FILL_CHANCE = 0.5
# Полной уверенности система не выдаёт: секцию могут отменить, а места
# сократить, и в снимках расписания этого не видно. Потолок нарочно высокий:
# он страхует только вырожденный случай "точно не заполнится", а не
# подрезает оценки в том диапазоне, где живёт большинство курсов.
MAX_CHANCE = 0.99


@dataclass
class Evidence:
    """Что известно про курс для этого студента — без единой выдуманной цифры."""

    course: Course
    on_plan: bool = False
    # Свободная позиция плана этого семестра, которую курс закрывает:
    # "Technical Elective". Позицию всё равно чем-то закрывать придётся.
    fills_slot: str | None = None
    covers: CourseKind | None = None
    prerequisites: bool | None = None
    missing: tuple[str, ...] = ()
    priority_tier: int | None = None
    # Вероятность, что курс заполнится, — из обученной модели. None означает
    # "модели нет", и тогда работает старое правило по средней заполняемости.
    fill_chance: float | None = None
    last_fill: float | None = None
    mean_fill: float | None = None
    terms_observed: int = 0
    ever_full: bool = False
    conflicts: tuple[str, ...] = ()

    @property
    def fills_up(self) -> float:
        """Вероятность, что курс вообще заполнится.

        Из обученной модели, если она есть. Если нет — старое правило:
        средняя заполняемость выше 100% означает "заполнится". Правило даёт
        только 0 или 1, и именно поэтому его заменяют моделью.
        """
        if self.fill_chance is not None:
            return self.fill_chance
        if self.mean_fill is None:
            return UNKNOWN_FILL_CHANCE
        return 1.0 if self.mean_fill >= 1.0 else 0.0

    @property
    def seat_chance(self) -> float:
        """Оценка шанса получить место.

        Задача распадается надвое: заполнится ли курс — и, если заполнится,
        достанется ли место именно этому тиру. Первое измеримо и обучено на
        истории регистраций, второе из имеющихся данных не выводится и
        остаётся предположением. Разделение нужно как раз затем, чтобы
        предположение не растворялось в общей формуле.

        Это оценка уровня курса и тира, а не персональная вероятность:
        данных о том, кому именно досталось место, в выгрузках нет.
        """
        filled = self.fills_up
        placed = TIER_PLACE.get(self.priority_tier, NO_TIER_PLACE)
        return min(MAX_CHANCE, (1.0 - filled) + filled * placed)

    @property
    def need(self) -> float:
        """Насколько курс нужен именно сейчас."""
        if self.on_plan:
            return 1.0
        if self.fills_slot is not None:
            return 0.9
        if self.covers is not None:
            return 0.7
        if self.course.kind is CourseKind.MAJOR:
            return 0.5
        return 0.3


@dataclass
class Recommendation:
    """Рекомендованный курс с объяснением и запасным вариантом."""

    course: Course
    score: float
    evidence: Evidence
    fallback: Course | None = None

    @property
    def why(self) -> str:
        parts = []
        if self.evidence.on_plan:
            parts.append("стоит в плане на этот семестр")
        elif self.evidence.fills_slot is not None:
            parts.append(f"закрывает позицию плана «{self.evidence.fills_slot}»")
        elif self.evidence.covers is not None:
            parts.append(f"закрывает {self.evidence.covers.value}")
        tier = self.evidence.priority_tier
        parts.append(f"приоритет: тир {tier}" if tier else "приоритета нет")
        # Модель смотрит на среднее по всем семестрам, и объяснение показывает
        # то же самое: иначе рядом стоят "заполнен на 92%" и "заполнится с
        # вероятностью 11%", и читать это невозможно.
        if self.evidence.terms_observed > 1 and self.evidence.mean_fill is not None:
            parts.append(f"в среднем заполнен на {self.evidence.mean_fill:.0%}")
        elif self.evidence.last_fill is not None:
            parts.append(f"в прошлый раз заполнен на {self.evidence.last_fill:.0%}")
        return "; ".join(parts)


def utility(need: float, access: float) -> float:
    """Взвешенная полезность курса."""
    weights = UTILITY_WEIGHTS
    return weights["need"] * need + weights["access"] * access


def build_evidence(
    course: Course,
    student: Student,
    semester: int,
    gaps: dict[CourseKind, int],
    tier: int | None = None,
    course_history=None,
    known_tests: dict[str, float] | None = None,
    slots: dict[str, str] | None = None,
    availability=None,
) -> Evidence:
    """Собрать всё известное про курс."""
    satisfied = (
        evaluate(course.requirement, student, known_tests)
        if course.requirement is not None
        else None
    )
    missing = tuple(
        sorted(code for code in course_codes(course.requirement) if student.grade_of(code) is None)
    )
    return Evidence(
        course=course,
        on_plan=course.recommended_semester == semester,
        fills_slot=(slots or {}).get(course.code),
        covers=course.kind if gaps.get(course.kind, 0) > 0 else None,
        prerequisites=satisfied,
        missing=missing,
        priority_tier=tier,
        fill_chance=availability.predict(course_history) if availability else None,
        last_fill=course_history.last_fill if course_history else None,
        mean_fill=course_history.mean_fill if course_history else None,
        terms_observed=course_history.terms if course_history else 0,
        ever_full=bool(course_history and course_history.ever_full),
    )


def _lectures(sections: list) -> list:
    """Лекционные секции курса: именно между ними студент выбирает."""
    lectures = [s for s in sections if s.kind == "L"]
    return lectures or sections


def _conflicts(code: str, others: list[str], sections: dict[str, list]) -> tuple[str, ...]:
    """С какими кандидатами курс несовместим по расписанию.

    Курс читают несколькими секциями, и студент берёт одну. Значит конфликт
    возникает, только если несовместима КАЖДАЯ пара секций: пока есть хоть
    одно сочетание без пересечения, курсы можно взять вместе. Сравниваем
    лекции — лабораторные и рецитации выбираются уже под них.
    """
    mine = _lectures(sections.get(code, []))
    if not mine:
        return ()

    clashing = []
    for other in others:
        theirs = _lectures(sections.get(other, []))
        if other == code or not theirs:
            continue
        if all(a.conflicts_with(b) for a in mine for b in theirs):
            clashing.append(other)
    return tuple(clashing)


def _fallback(evidence: Evidence, pool: list[Evidence]) -> Course | None:
    """Запасной курс: закрывает то же требование, но попасть на него проще."""
    same = [
        other
        for other in pool
        if other.course.code != evidence.course.code
        and other.course.kind is evidence.course.kind
        and other.seat_chance > evidence.seat_chance
    ]
    if not same:
        return None
    return max(same, key=lambda e: e.seat_chance).course


def recommend(
    program,
    student: Student,
    semester: int,
    offerings: dict | None = None,
    fill_history: dict | None = None,
    sections: dict[str, list] | None = None,
    school: str | None = None,
    term: str | None = None,
    availability=None,
    limit: int = 5,
    known_tests: dict[str, float] | None = None,
) -> list[Recommendation]:
    """Ранжировать курсы, доступные студенту в этом семестре.

    offerings — курсы каталога (тиры приоритета), term — семестр регистрации,
    за который эти тиры брать, fill_history — заполняемость прошлых семестров,
    availability — обученная модель заполняемости, sections — секции семестра
    для проверки конфликтов по времени. Любой из источников можно не передавать: тогда
    соответствующее свидетельство просто отсутствует, а не подменяется нулём.
    """
    offerings = offerings or {}
    fill_history = fill_history or {}
    sections = sections or {}

    gaps = remaining_requirements(program.requirements, program.courses, student)
    available = eligible_courses(
        program.catalog, student, semester, respect_plan=True, known_tests=known_tests
    )
    # Свободные позиции этого семестра: что бы студент ни выбрал, закрыть их
    # чем-то нужно, и курс, который их закрывает, нужнее произвольного.
    open_slots = {
        code: slot.name
        for slot in program.slots
        if slot.semester == semester
        for code in slot.eligible_codes
    }

    pool = []
    for course in available:
        offering = offerings.get(course.code)
        tier = (
            offering.priority_for(student.year, school, program.name, term)
            if offering is not None and school is not None
            else None
        )
        pool.append(
            build_evidence(
                course,
                student,
                semester,
                gaps,
                tier=tier,
                course_history=fill_history.get(course.code),
                known_tests=known_tests,
                slots=open_slots,
                availability=availability,
            )
        )

    ranked = sorted(pool, key=lambda e: utility(e.need, e.seat_chance), reverse=True)[:limit]
    codes = [e.course.code for e in ranked]
    recommendations = []
    for evidence in ranked:
        evidence.conflicts = _conflicts(evidence.course.code, codes, sections)
        recommendations.append(
            Recommendation(
                course=evidence.course,
                score=utility(evidence.need, evidence.seat_chance),
                evidence=evidence,
                fallback=_fallback(evidence, pool),
            )
        )
    return recommendations


def main() -> None:
    import argparse
    from pathlib import Path

    from .data.assemble import attach_catalog, attach_electives, load_programs
    from .data.catalog import Catalog, from_pdfs
    from .data.catalog import load as load_catalog
    from .data.schedule import history
    from .data.schedule import parse_pdf as parse_schedule
    from .data.transcripts import parse_pdf as parse_transcript
    from .domain import CompletedCourse
    from .models.availability import can_train, observations
    from .models.availability import load as load_availability
    from .models.availability import train as train_availability

    parser = argparse.ArgumentParser(description="Что брать в следующем семестре")
    parser.add_argument("--transcript", type=Path, help="PDF транскрипта — настоящее пройденное")
    parser.add_argument("--admission-year", type=int, help="год поступления")
    parser.add_argument("--program", help="часть названия специальности")
    parser.add_argument("--school", help="школа студента: SCAI, SSH, SoE, SoM, GSB, SMG")
    parser.add_argument("--semester", type=int, help="целевой семестр, 1..8")
    parser.add_argument(
        "--completed-through",
        type=int,
        default=0,
        help="без транскрипта: считать пройденными все курсы плана по этот семестр",
    )
    parser.add_argument("--gpa", type=float, default=3.0)
    parser.add_argument(
        "--requirements",
        type=Path,
        nargs="*",
        default=[],
        help="PDF Course Requirements: можно несколько, тогда известны и весенние курсы",
    )
    parser.add_argument("--catalog", type=Path, help="собранный catalog.json вместо PDF")
    parser.add_argument("--term", help='семестр регистрации: "Fall 2026"')
    parser.add_argument("--schedule", type=Path, nargs="*", default=[], help="PDF расписаний")
    parser.add_argument(
        "--availability", type=Path, help="обученная модель заполняемости (JSON)"
    )
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    transcript = None
    if args.transcript:
        transcript = parse_transcript(args.transcript)
        if transcript.is_partial:
            parser.error(
                f"в файле не все страницы транскрипта: разобрано {transcript.earned} кредитов "
                f"из {transcript.credits_earned}"
            )

    year = args.admission_year or (transcript.admission_year if transcript else None)
    name = args.program or (transcript.major if transcript else None)
    school = args.school or (transcript.school_code if transcript else None)
    if not year or not name:
        parser.error("нужен --transcript либо --admission-year вместе с --program")

    programs = load_programs(year)
    matches = [p for key, p in programs.items() if name.upper() in key]
    if not matches:
        parser.error(f"специальность не найдена: {name}")
    program = matches[0]
    # Следующий семестр после последнего пройденного, если он не задан явно.
    semester = args.semester or (transcript.next_semester if transcript else None)
    if not semester:
        parser.error("нужен --semester либо --transcript, по которому его видно")

    catalog = Catalog()
    if args.catalog:
        catalog = load_catalog(args.catalog)
    elif args.requirements:
        catalog = from_pdfs(args.requirements)
    # Семестр регистрации: по умолчанию самый поздний из известных каталогу.
    term = args.term or (catalog.terms[-1] if catalog.terms else None)
    if len(catalog):
        attach_catalog({program.name: program}, catalog, term)
        attach_electives({program.name: program}, catalog, term)
    offerings = catalog.entries

    snapshots = [parse_schedule(path).filter_level("UG") for path in args.schedule]
    fill_history = history(snapshots)

    # Модель учится на семестрах строго до целевого: иначе она знает ответ.
    availability = None
    if args.availability:
        availability = load_availability(args.availability)
    elif snapshots:
        rows = observations(snapshots)
        if can_train(rows, term):
            availability = train_availability(rows, before=term)
    current = next(
        (s for s in snapshots if not s.is_pre_registration),
        None,
    )
    sections = current.by_course() if current else {}

    if transcript is not None:
        student = transcript.student()
    else:
        # Без транскрипта остаётся допущение "шёл строго по плану". Оно
        # заведомо неверно для конкретного студента и годится только чтобы
        # посмотреть, что система советует потоку вообще.
        student = Student(
            "student",
            major=program.name,
            year=(semester + 1) // 2,
            gpa=args.gpa,
            completed=[
                CompletedCourse(course.code, 3.0, index, credits=course.credits)
                for index in range(1, args.completed_through + 1)
                for course in program.semester_courses(index)
            ],
        )

    print(f"{program.degree} in {program.name}, семестр {semester}")
    print(f"пройдено курсов: {len(student.completed)}, кредитов: {student.earned_credits}")
    if availability is not None:
        print(f"модель заполняемости: {availability.describe()}")
    print()

    results = recommend(
        program,
        student,
        semester,
        offerings=offerings,
        fill_history=fill_history,
        sections=sections,
        school=school,
        term=term,
        availability=availability,
        limit=args.limit,
    )
    if not results:
        print("подходящих курсов не нашлось")
        return

    for result in results:
        evidence = result.evidence
        print(f"{result.course.code:10s} {result.course.title[:40]:42s} балл {result.score:.2f}")
        print(f"   {result.why}")
        print(f"   шанс получить место ≈ {evidence.seat_chance:.0%}", end="")
        if evidence.fill_chance is not None:
            print(f"   (заполнится с вероятностью {evidence.fill_chance:.0%}, "
                  f"семестров в истории: {evidence.terms_observed})")
        else:
            print(f"   (семестров в истории: {evidence.terms_observed})")
        if evidence.missing:
            print(f"   не хватает: {', '.join(evidence.missing)}")
        if evidence.conflicts:
            print(f"   несовместим по времени с: {', '.join(evidence.conflicts)}")
        if result.fallback is not None:
            print(f"   запасной вариант: {result.fallback.code}")
        print()


if __name__ == "__main__":
    main()
