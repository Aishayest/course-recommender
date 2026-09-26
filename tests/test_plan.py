from datetime import time

from course_recommender.data.assemble import PlanSlot, Program
from course_recommender.data.grades import CourseGrades, SectionGrades
from course_recommender.data.schedule import Meeting, Section
from course_recommender.domain import Course, CourseKind
from course_recommender.plan import (
    assemble,
    describe,
    fits,
    lectures,
    practice_count,
    rank_sections,
    target_credits,
)
from course_recommender.recommend import Evidence


def course(code, credits=6):
    return Course(code=code, title=code, credits=credits, kind=CourseKind.ELECTIVE)


def evidence(code, credits=6, *, need_slot="Technical Elective", on_plan=False, grades=None):
    return Evidence(
        course=course(code, credits), fills_slot=need_slot, on_plan=on_plan, grades=grades
    )


def section(code, label="1L", days=("M",), start=time(9, 0), end=time(9, 50), faculty=()):
    return Section(
        term="Fall 2026", code=code, section=label,
        meetings=[Meeting(days, start, end)], faculty=tuple(faculty),
    )


def grades_for(code, records):
    """records: {преподаватель: средний балл}"""
    return CourseGrades(
        code=code, title=code,
        sections=[
            SectionGrades(
                term="Fall 2025", school="SEDS", department="CS", code=code, title=code,
                section=i + 1, graded=20, average=average, deviation=0.5, median=average,
                shares={}, letters=20, instructors=(name,),
            )
            for i, (name, average) in enumerate(records.items())
        ],
    )


def test_lectures_prefer_the_lecture_component():
    sections = [section("A 101", "1L"), section("A 101", "1Lb"), section("A 101", "2L")]
    assert [s.section for s in lectures(sections)] == ["1L", "2L"]


def test_lectures_fall_back_when_there_is_no_lecture():
    sections = [section("A 101", "1S")]
    assert lectures(sections) == sections


def test_practice_count():
    sections = [section("A 101", "1L"), section("A 101", "1Lb"), section("A 101", "2R")]
    assert practice_count(sections) == 2


def test_fits_detects_a_clash_with_what_is_already_chosen():
    chosen = assemble([evidence("A 101")], {"A 101": [section("A 101")]}, 6).choices
    assert not fits(section("B 101"), chosen)  # то же время
    assert fits(section("B 101", start=time(11, 0), end=time(11, 50)), chosen)


def test_sections_are_ranked_by_what_the_instructor_did_before():
    options = [
        section("A 101", "1L", faculty=("Слабый",)),
        section("A 101", "2L", faculty=("Сильный",)),
        section("A 101", "3L", faculty=("Неизвестный",)),
    ]
    ranked = rank_sections(options, grades_for("A 101", {"Слабый": 2.0, "Сильный": 3.5}))
    # Сначала лучший результат, неизвестные — следом, а не в конце очереди позора
    assert [s.section for s in ranked][:2] == ["2L", "1L"]


def test_assemble_fills_up_to_the_target():
    pool = [evidence(f"A {100 + i}") for i in range(6)]
    sections = {f"A {100 + i}": [section(f"A {100 + i}", start=time(9 + i), end=time(9 + i, 50))] for i in range(6)}
    capacity = {"Technical Elective": 6}
    built = assemble(pool, sections, target_credits=18, capacity=capacity)
    assert built.credits == 18
    assert len(built.choices) == 3


def test_assemble_avoids_time_conflicts():
    # Оба курса идут в одно время — вместе их не взять
    pool = [evidence("A 101"), evidence("B 101")]
    sections = {"A 101": [section("A 101")], "B 101": [section("B 101")]}
    built = assemble(pool, sections, target_credits=12, capacity={"Technical Elective": 2})
    assert len(built.choices) == 1
    reason = {e.course.code: why for e, why in built.left_out}
    assert "пересекается" in next(iter(reason.values()))


def test_assemble_takes_the_free_section_of_a_course():
    pool = [evidence("A 101"), evidence("B 101")]
    sections = {
        "A 101": [section("A 101")],
        "B 101": [section("B 101"), section("B 101", "2L", start=time(13, 0), end=time(13, 50))],
    }
    built = assemble(pool, sections, target_credits=12, capacity={"Technical Elective": 2})
    assert built.codes == ("A 101", "B 101")
    assert [c.label for c in built.choices] == ["1L", "2L"]


def test_assemble_does_not_take_more_than_there_are_open_positions():
    pool = [evidence(f"A {100 + i}") for i in range(4)]
    sections = {f"A {100 + i}": [section(f"A {100 + i}", start=time(9 + i), end=time(9 + i, 50))] for i in range(4)}
    built = assemble(pool, sections, target_credits=30, capacity={"Technical Elective": 2})
    assert len(built.choices) == 2
    reasons = [why for _, why in built.left_out]
    assert any("уже закрыты" in why for why in reasons)


def test_required_course_is_taken_regardless_of_positions():
    pool = [evidence("A 101", on_plan=True, need_slot=None), evidence("B 101")]
    sections = {c: [section(c, start=time(9 + i), end=time(9 + i, 50))] for i, c in enumerate(("A 101", "B 101"))}
    built = assemble(pool, sections, target_credits=12, capacity={})
    assert "A 101" in built.codes


def test_course_without_a_schedule_is_taken_but_flagged():
    built = assemble([evidence("A 101")], {}, target_credits=6, capacity={"Technical Elective": 1})
    assert built.codes == ("A 101",)
    assert built.unscheduled == built.choices
    assert "время не проверено" in "\n".join(describe(built))


def test_missing_credits_are_reported():
    built = assemble([evidence("A 101")], {}, target_credits=30, capacity={"Technical Elective": 1})
    assert built.missing_credits == 24
    assert "не хватает 24 ECTS" in "\n".join(describe(built))


def test_target_credits_come_from_the_plan():
    program = Program(
        admission_year=2023, name="CS", degree="BSc",
        courses={"A 101": Course("A 101", "A", 6, CourseKind.MAJOR, recommended_semester=7)},
        slots=[PlanSlot(name="Technical Elective", semester=7, term="fall", credits=6)],
    )
    assert target_credits(program, 7) == 12
    assert target_credits(program, 3) == 30  # в плане пусто — берём обычную нагрузку


def test_describe_shows_time_and_alternatives():
    pool = [evidence("A 101")]
    sections = {"A 101": [section("A 101", "1L", faculty=("Кто-то",)), section("A 101", "2L", start=time(15, 0), end=time(15, 50))]}
    built = assemble(pool, sections, target_credits=6, capacity={"Technical Elective": 1})
    text = "\n".join(describe(built))
    assert "M 09:00-09:50" in text
    assert "ведёт Кто-то" in text
    assert "другие секции: 2L" in text
