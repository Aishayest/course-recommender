"""Сборка семестра: что взять вместе и на какие секции идти.

Ранжированный список курсов — ещё не ответ. На регистрацию студент несёт
набор: столько-то кредитов, без пересечений по времени, закрывающий то, что
осталось по плану. Собрать его из топ-5 он должен был сам, и это ровно та
работа, которую система обязана делать за него.

Планируется по лекциям. Лабораторные и рецитации в расписании есть, но их
номера с лекционными не совпадают: у PHYS 161 три лекции и тридцать
лабораторных, и выбираются они отдельно. Поэтому лекции расставляются здесь,
а практика остаётся студенту — с оговоркой в отчёте, сколько у неё вариантов.

Секция выбирается не наугад. Когда лекций у курса несколько, они читаются по
одной программе за одни кредиты, и разница между ними — только время и
преподаватель. Предпочесть секцию, у которой преподаватель раньше выводил
группу лучше, — это не выбор курса полегче, а выбор из одинакового.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .data.grades import CourseGrades
from .domain import Course
from .recommend import Evidence

# Компоненты, которые студент выбирает отдельно от лекции.
PRACTICE = frozenset({"Lb", "PLb", "CLb", "ChLb", "R", "T", "S", "P"})
DEFAULT_CREDITS = 30
# Сколько вариантов практики считается достаточным, чтобы не предупреждать.
ENOUGH_PRACTICE = 2


@dataclass(frozen=True)
class Choice:
    """Курс и лекционная секция, на которую идти."""

    evidence: Evidence
    section: object | None = None
    alternatives: tuple = ()
    practice: int = 0

    @property
    def course(self) -> Course:
        return self.evidence.course

    @property
    def credits(self) -> int:
        return self.course.credits

    @property
    def label(self) -> str:
        return getattr(self.section, "section", "") if self.section else ""

    @property
    def instructors(self) -> tuple[str, ...]:
        return tuple(getattr(self.section, "faculty", ())) if self.section else ()

    @property
    def practice_is_tight(self) -> bool:
        """Практику ещё выбирать, и вариантов у неё мало."""
        return 0 < self.practice < ENOUGH_PRACTICE


@dataclass
class Semester:
    """Собранный семестр."""

    term: str = ""
    target_credits: int = DEFAULT_CREDITS
    choices: list[Choice] = field(default_factory=list)
    # Что не вошло и почему — чтобы решение было видно, а не только результат.
    left_out: list[tuple[Evidence, str]] = field(default_factory=list)

    @property
    def credits(self) -> int:
        return sum(choice.credits for choice in self.choices)

    @property
    def missing_credits(self) -> int:
        return max(0, self.target_credits - self.credits)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(choice.course.code for choice in self.choices)

    @property
    def unscheduled(self) -> list[Choice]:
        """Курсы, для которых расписание неизвестно."""
        return [choice for choice in self.choices if choice.section is None]


def lectures(sections: list) -> list:
    """Лекционные секции курса: между ними студент и выбирает."""
    found = [s for s in sections if s.kind == "L"]
    return found or [s for s in sections if s.kind not in PRACTICE] or sections


def practice_count(sections: list) -> int:
    """Сколько у курса секций практики, которые предстоит выбрать отдельно."""
    return sum(1 for s in sections if s.kind in PRACTICE)


def fits(section, chosen: list[Choice]) -> bool:
    """Влезает ли секция в уже выбранное."""
    return not any(
        choice.section is not None and section.conflicts_with(choice.section)
        for choice in chosen
    )


def rank_sections(
    course_sections: list, grades: CourseGrades | None, preferred: str | None = None
) -> list:
    """Порядок предпочтения секций.

    Выбор студента идёт первым: он мог предпочесть время или преподавателя
    по причинам, которых в данных нет. Дальше — те, чей преподаватель раньше
    выводил группу лучше. Про кого ничего не известно, идут следом: незнание
    не повод ни продвигать секцию, ни задвигать её.
    """
    records = {r.name: r.average for r in grades.instructors()} if grades else {}

    def key(section):
        known = [records[name] for name in section.faculty if name in records]
        return (
            0 if preferred and section.section == preferred else 1,
            0 if known else 1,
            -(max(known) if known else 0.0),
            section.number or 0,
        )

    return sorted(course_sections, key=key)


def _has_room(evidence: Evidence, chosen: list[Choice], capacity: dict[str, int]) -> bool:
    """Осталась ли незакрытая позиция, которую курс закрывает.

    Обязательный курс плана берут всегда. А вот четвёртый технический
    электив при трёх открытых позициях закрывать уже нечего: он пойдёт
    сверх программы, и предлагать его наравне с нужным нельзя.
    """
    if evidence.on_plan or evidence.fills_slot is None:
        return True
    taken = Counter(c.evidence.fills_slot for c in chosen)
    return taken[evidence.fills_slot] < capacity.get(evidence.fills_slot, 0)


def _search(
    pool: list[tuple[Evidence, list]],
    target: int,
    index: int,
    chosen: list[Choice],
    credits: int,
    best: dict,
    capacity: dict[str, int],
    prefer: dict[str, str],
) -> None:
    """Перебор с отсечением: максимум пользы в пределах целевых кредитов."""
    score = sum(c.evidence.need + c.evidence.seat_chance for c in chosen)
    if (score, credits) > (best["score"], best["credits"]):
        best.update(score=score, credits=credits, choices=list(chosen))

    if index >= len(pool) or credits >= target:
        return

    evidence, course_sections = pool[index]
    cost = evidence.course.credits
    if credits + cost <= target and _has_room(evidence, chosen, capacity):
        options = rank_sections(
            lectures(course_sections), evidence.grades, prefer.get(evidence.course.code)
        )
        available = [s for s in options if fits(s, chosen)]
        if available:
            chosen.append(
                Choice(
                    evidence=evidence,
                    section=available[0],
                    alternatives=tuple(available[1:]),
                    practice=practice_count(course_sections),
                )
            )
            _search(pool, target, index + 1, chosen, credits + cost, best, capacity, prefer)
            chosen.pop()
        elif not course_sections:
            # Расписания нет — курс ставим, но время не проверено.
            chosen.append(Choice(evidence=evidence))
            _search(pool, target, index + 1, chosen, credits + cost, best, capacity, prefer)
            chosen.pop()

    _search(pool, target, index + 1, chosen, credits, best, capacity, prefer)


def assemble(
    pool: list[Evidence],
    sections: dict[str, list] | None = None,
    target_credits: int = DEFAULT_CREDITS,
    term: str = "",
    capacity: dict[str, int] | None = None,
    prefer: dict[str, str] | None = None,
) -> Semester:
    """Собрать семестр из отранжированных кандидатов.

    Кандидаты уже прошли через ограничения: пререквизиты выполнены, курс
    читается в этом семестре. Здесь решается только, что из них берётся
    вместе — по кредитам, по времени и по числу ещё не закрытых позиций.

    prefer — секции, выбранные студентом: их пробуют первыми. Если выбранная
    не сходится по времени с остальным, берётся другая, и в отчёте это видно.
    """
    sections = sections or {}
    ordered = sorted(pool, key=lambda e: -(e.need + e.seat_chance))
    prepared = [(evidence, sections.get(evidence.course.code, [])) for evidence in ordered]
    capacity = capacity if capacity is not None else _capacity_of(ordered)

    best: dict = {"score": -1.0, "credits": 0, "choices": []}
    _search(prepared, target_credits, 0, [], 0, best, capacity, prefer or {})

    chosen = best["choices"]
    taken = {choice.course.code for choice in chosen}
    left_out = [
        (evidence, _why_not(evidence, chosen, sections, target_credits, best["credits"]))
        for evidence in ordered
        if evidence.course.code not in taken
    ]
    return Semester(
        term=term, target_credits=target_credits, choices=chosen, left_out=left_out
    )


def _capacity_of(pool: list[Evidence]) -> dict[str, int]:
    """Сколько позиций каждого вида считать открытыми, если не сказано иначе.

    Без данных аудита остаётся предположить, что позиция одна: так система
    хотя бы не набьёт семестр четырьмя элективами одного вида.
    """
    return {evidence.fills_slot: 1 for evidence in pool if evidence.fills_slot}


def _why_not(
    evidence: Evidence,
    chosen: list[Choice],
    sections: dict[str, list],
    target: int,
    credits: int,
) -> str:
    """Почему курс не вошёл в семестр."""
    course_sections = lectures(sections.get(evidence.course.code, []))
    if course_sections and not any(fits(s, chosen) for s in course_sections):
        clashing = sorted(
            choice.course.code
            for choice in chosen
            if choice.section is not None
            and all(s.conflicts_with(choice.section) for s in course_sections)
        )
        return f"пересекается по времени с {', '.join(clashing)}" if clashing else "не влезает по времени"
    if credits + evidence.course.credits > target:
        return "не хватает кредитов в семестре"
    if evidence.fills_slot and not evidence.on_plan:
        taken = sum(1 for c in chosen if c.evidence.fills_slot == evidence.fills_slot)
        if taken:
            return f"позиции «{evidence.fills_slot}» уже закрыты"
    return "нашлось что-то нужнее"


def target_credits(program, semester: int) -> int:
    """Нагрузка семестра по учебному плану."""
    courses = sum(
        c.credits for c in program.courses.values() if c.recommended_semester == semester
    )
    slots = sum(s.credits or 0 for s in program.slots if s.semester == semester)
    return (courses + slots) or DEFAULT_CREDITS


def describe(semester: Semester) -> list[str]:
    """Человекочитаемый отчёт о собранном семестре."""
    lines = [
        (
            f"семестр собран: {semester.credits} ECTS из {semester.target_credits}, "
            f"курсов {len(semester.choices)}"
        )
    ]
    if semester.missing_credits:
        lines.append(f"не хватает {semester.missing_credits} ECTS — закрыть нечем")

    for choice in semester.choices:
        label = f" секция {choice.label}" if choice.label else ""
        lines.append(f"  {choice.course.code:10s}{label:12s} {choice.credits:2d} ECTS  "
                     f"{choice.course.title[:38]}")
        when = _timetable(choice.section)
        if when:
            lines.append(f"      {when}")
        if choice.instructors:
            lines.append(f"      ведёт {', '.join(choice.instructors)}")
        if choice.alternatives:
            other = ", ".join(getattr(s, "section", "?") for s in choice.alternatives)
            lines.append(f"      другие секции: {other}")
        if choice.practice_is_tight:
            lines.append(f"      практику выбирать отдельно, вариантов {choice.practice}")
        if choice.section is None:
            lines.append("      расписание неизвестно, время не проверено")
    return lines


def _timetable(section) -> str:
    """Дни и часы секции одной строкой."""
    if section is None:
        return ""
    parts = []
    for meeting in getattr(section, "meetings", ()):
        if meeting.online:
            parts.append("онлайн")
        elif meeting.days and meeting.start and meeting.end:
            days = "".join(meeting.days)
            parts.append(f"{days} {meeting.start:%H:%M}-{meeting.end:%H:%M}")
    return "; ".join(parts)
