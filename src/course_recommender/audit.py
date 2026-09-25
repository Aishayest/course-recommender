"""Что студенту осталось до диплома.

Рекомендация отвечает на вопрос "что взять в следующем семестре", но перед
ним стоит другой: что вообще осталось. До сих пор система отвечала на него
допущением — считала пройденным всё, что стоит в плане по такой-то семестр.
Реальная траектория так не выглядит: курсы пересдают, берут не в свой семестр,
закрывают элективом то, что сосед закрыл другим.

Здесь этого допущения нет. На вход идёт настоящий список пройденного, и каждый
курс разносится по тому, что он закрывает: обязательную позицию плана, свободную
позицию или ничего. Разнести можно не всё, и это видно в отчёте отдельной
строкой: handbook не про каждую позицию говорит, чем её закрывают, и выдумывать
за него нельзя — иначе аудит покажет диплом там, где его нет.

    uv run python -m course_recommender.audit --transcript student_transcript.pdf
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data.assemble import PlanSlot, Program
from .domain import CompletedCourse, Course, CourseKind, Student, grade_points

# Позиции, которые закрываются чем угодно: "Open Elective", "Free Elective".
# Их добирают в последнюю очередь, когда профильные позиции уже разобраны.
OPEN_KINDS = frozenset({"general"})


@dataclass(frozen=True)
class SlotStatus:
    """Свободная позиция плана и то, чем она закрыта."""

    slot: PlanSlot
    closed_by: str | None = None

    @property
    def is_closed(self) -> bool:
        return self.closed_by is not None

    @property
    def is_checkable(self) -> bool:
        """Известно ли вообще, чем эту позицию закрывают.

        У "Technical Elective" список есть, у "Kazakh Language" — нет:
        handbook нигде не перечисляет, какие курсы её закрывают. Такую
        позицию честнее показать непроверенной, чем закрыть наугад.
        """
        return bool(self.slot.eligible_codes) or self.slot.kind in OPEN_KINDS


@dataclass
class Audit:
    """Состояние студента относительно программы."""

    program: Program
    student: Student
    done: list[Course] = field(default_factory=list)
    missing: list[Course] = field(default_factory=list)
    # Пройден, но ниже проходной оценки плана — позиция не закрыта.
    low_grade: list[tuple[Course, float]] = field(default_factory=list)
    in_progress: list[CompletedCourse] = field(default_factory=list)
    slots: list[SlotStatus] = field(default_factory=list)
    # Пройденное, что не легло ни в одну позицию программы.
    extra: list[CompletedCourse] = field(default_factory=list)
    degree_credits: int | None = None

    @property
    def earned_credits(self) -> int:
        return self.student.earned_credits

    @property
    def remaining_credits(self) -> int | None:
        if self.degree_credits is None:
            return None
        return max(0, self.degree_credits - self.earned_credits)

    @property
    def open_slots(self) -> list[SlotStatus]:
        return [s for s in self.slots if not s.is_closed]

    @property
    def unchecked_slots(self) -> list[SlotStatus]:
        """Позиции, про которые неизвестно, закрыты они или нет."""
        return [s for s in self.slots if not s.is_closed and not s.is_checkable]

    @property
    def is_complete(self) -> bool:
        """Программа выполнена — насколько это вообще можно проверить."""
        return not self.missing and not self.low_grade and not self.open_slots


def plan_credits(program: Program) -> int:
    """Кредиты всей программы: обязательные курсы плюс свободные позиции.

    Handbook называет сумму на диплом не для всех специальностей, но план
    расписан у всех, и сумма по нему совпадает с официальной: у CS выпуска
    2023 это 240 ECTS и там, и там.
    """
    courses = sum(c.credits for c in program.courses.values() if c.recommended_semester)
    return courses + sum(slot.credits or 0 for slot in program.slots)


def meets_grade(grade: float | None, minimum: str | None) -> bool:
    """Достаточна ли оценка для зачёта позиции плана."""
    if grade is None:
        return False
    required = grade_points(minimum)
    return required is None or grade >= required


def _plan_courses(program: Program) -> list[Course]:
    return sorted(
        (c for c in program.courses.values() if c.recommended_semester is not None),
        key=lambda c: (c.recommended_semester, c.code),
    )


def _fill_slots(
    slots: list[PlanSlot], leftovers: dict[str, CompletedCourse]
) -> tuple[list[SlotStatus], dict[str, CompletedCourse]]:
    """Разнести оставшееся пройденное по свободным позициям.

    Сначала позиции с самым узким списком: если курс закрывает и технический
    электив, и естественнонаучный, отдать его надо туда, где замены меньше.
    Позиции "на что угодно" разбираются последними — их закроет что угодно,
    а профильную позицию закрыть нечем.
    """
    statuses: dict[int, SlotStatus] = {}
    order = sorted(
        range(len(slots)),
        key=lambda i: (
            slots[i].kind in OPEN_KINDS,
            len(slots[i].eligible_codes) if slots[i].eligible_codes else 10**6,
        ),
    )

    for index in order:
        slot = slots[index]
        if slot.eligible_codes:
            candidates = [code for code in sorted(leftovers) if code in slot.eligible_codes]
        elif slot.kind in OPEN_KINDS:
            candidates = sorted(leftovers)
        else:
            # Чем закрывается позиция, неизвестно — оставляем непроверенной.
            statuses[index] = SlotStatus(slot=slot)
            continue

        if candidates:
            statuses[index] = SlotStatus(slot=slot, closed_by=candidates[0])
            leftovers.pop(candidates[0])
        else:
            statuses[index] = SlotStatus(slot=slot)

    return [statuses[i] for i in range(len(slots))], leftovers


def audit(program: Program, student: Student) -> Audit:
    """Разобрать пройденное студентом по позициям программы."""
    taken = {c.code: c for c in student.completed}
    result = Audit(program=program, student=student, degree_credits=program.total_credits or plan_credits(program))

    used: set[str] = set()
    for course in _plan_courses(program):
        completed = taken.get(course.code)
        if completed is None:
            result.missing.append(course)
            continue
        used.add(course.code)
        if completed.grade is None:
            result.in_progress.append(completed)
        elif meets_grade(completed.grade, course.min_grade):
            result.done.append(course)
        else:
            result.low_grade.append((course, completed.grade))

    leftovers = {
        code: completed
        for code, completed in taken.items()
        if code not in used and completed.is_earned
    }
    result.slots, leftovers = _fill_slots(program.slots, leftovers)
    result.extra = sorted(leftovers.values(), key=lambda c: c.code)
    result.in_progress.extend(
        completed for code, completed in taken.items()
        if code not in used and completed.grade is None
    )
    return result


def remaining_by_kind(result: Audit) -> dict[CourseKind, int]:
    """Сколько кредитов какой категории ещё не закрыто."""
    remaining: dict[CourseKind, int] = {}
    for course in result.missing:
        remaining[course.kind] = remaining.get(course.kind, 0) + course.credits
    for status in result.open_slots:
        remaining[CourseKind.ELECTIVE] = (
            remaining.get(CourseKind.ELECTIVE, 0) + (status.slot.credits or 0)
        )
    return remaining


def main() -> None:
    import argparse
    from pathlib import Path

    from .data.assemble import attach_catalog, attach_electives, load_programs
    from .data.catalog import from_pdfs
    from .data.catalog import load as load_catalog
    from .data.transcripts import parse_pdf as parse_transcript

    parser = argparse.ArgumentParser(description="Что студенту осталось до диплома")
    parser.add_argument("transcript", type=Path, help="PDF транскрипта")
    parser.add_argument("--program", help="специальность, если в транскрипте её нет")
    parser.add_argument("--admission-year", type=int, help="год поступления, если его нет")
    parser.add_argument("--catalog", type=Path, nargs="*", default=[],
                        help="catalog.json или PDF Course Requirements — раскрыть элективы")
    parser.add_argument("--term", help='семестр каталога: "Fall 2026"')
    args = parser.parse_args()

    transcript = parse_transcript(args.transcript)
    if transcript.is_partial:
        parser.error(
            f"в файле не все страницы транскрипта: разобрано {transcript.earned} кредитов "
            f"из {transcript.credits_earned}. Аудит по нему соврёт."
        )

    year = args.admission_year or transcript.admission_year
    name = args.program or transcript.major
    if not year or not name:
        parser.error("в транскрипте нет года поступления или специальности — задайте их явно")

    programs = load_programs(year)
    matches = [p for key, p in programs.items() if name.upper() in key]
    if not matches:
        parser.error(f"специальность не найдена в handbook {year}: {name}")
    program = matches[0]

    if args.catalog:
        catalog = (
            load_catalog(args.catalog[0])
            if len(args.catalog) == 1 and args.catalog[0].suffix == ".json"
            else from_pdfs(args.catalog)
        )
        attach_catalog({program.name: program}, catalog, args.term)
        attach_electives({program.name: program}, catalog, args.term)

    student = transcript.student()
    result = audit(program, student)

    print(f"{transcript.name or student.student_id} — {program.degree} in {program.name}")
    print(f"поступление: {transcript.admission_term}, GPA {transcript.gpa}")
    total = result.degree_credits
    print(f"кредитов: {result.earned_credits} из {total}, осталось {result.remaining_credits}")
    print()

    if result.missing:
        print(f"не пройдено обязательных курсов: {len(result.missing)}")
        for course in result.missing:
            print(f"   сем {course.recommended_semester}  {course.code:10s} {course.credits:2d} ECTS  {course.title[:44]}")
    if result.low_grade:
        print(f"\nпройдено ниже проходной оценки: {len(result.low_grade)}")
        for course, grade in result.low_grade:
            print(f"   {course.code:10s} получено {grade:.2f}, нужно {course.min_grade}  {course.title[:40]}")
    if result.in_progress:
        print(f"\nбез результата: {len(result.in_progress)}")
        for course in result.in_progress:
            print(f"   {course.code:10s} {course.term}  {course.title[:44]}")

    print(f"\nсвободные позиции плана: закрыто {len(result.slots) - len(result.open_slots)} из {len(result.slots)}")
    for status in result.slots:
        if status.is_closed:
            mark, note = "+", f"закрыт: {status.closed_by}"
        elif status.slot.eligible_codes:
            mark, note = "-", f"вариантов: {len(status.slot.eligible_codes)}"
        elif status.is_checkable:
            mark, note = "-", "закрывается любым курсом"
        else:
            mark, note = "?", "чем закрывается — handbook не говорит"
        print(f"   {mark} сем {status.slot.semester}  {status.slot.name[:34]:36s} {note}")

    if result.extra:
        print(f"\nсверх программы: {len(result.extra)}")
        for course in result.extra:
            print(f"   {course.code:10s} {course.credits:2d} ECTS  {course.title[:44]}")

    unchecked = result.unchecked_slots
    if unchecked:
        print(f"\nнепроверенных позиций: {len(unchecked)} — аудит по ним ничего не утверждает")


if __name__ == "__main__":
    main()
