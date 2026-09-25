from course_recommender.audit import (
    Audit,
    audit,
    meets_grade,
    plan_credits,
    remaining_by_kind,
)
from course_recommender.data.assemble import PlanSlot, Program
from course_recommender.domain import CompletedCourse, Course, CourseKind, Student


def course(code, semester=1, credits=6, kind=CourseKind.MAJOR, min_grade=None):
    return Course(
        code=code, title=code, credits=credits, kind=kind,
        min_grade=min_grade, recommended_semester=semester,
    )


def slot(name, semester=7, credits=6, kind=None, codes=()):
    return PlanSlot(
        name=name, semester=semester, term="fall", credits=credits,
        kind=kind, eligible_codes=frozenset(codes),
    )


def program(*, courses=(), slots=(), total=None):
    return Program(
        admission_year=2023,
        name="COMPUTER SCIENCE (CS)",
        degree="BSc",
        courses={c.code: c for c in courses},
        slots=list(slots),
        total_credits=total,
    )


def student(*taken):
    return Student("s1", "COMPUTER SCIENCE (CS)", 4, 3.0, list(taken))


def done(code, grade=3.0, credits=6, semester=1):
    return CompletedCourse(code=code, grade=grade, semester=semester, credits=credits, title=code)


def test_plan_credits_counts_courses_and_open_positions():
    assert plan_credits(program(courses=[course("CSCI 151", credits=8)], slots=[slot("Elective")])) == 14


def test_meets_grade():
    assert meets_grade(3.0, None)
    assert meets_grade(1.67, "C-")
    assert not meets_grade(1.0, "C-")
    assert not meets_grade(None, None)  # результата нет — позиция не закрыта


def test_audit_splits_plan_into_done_and_missing():
    result = audit(
        program(courses=[course("CSCI 151"), course("CSCI 152", semester=2)]),
        student(done("CSCI 151")),
    )
    assert [c.code for c in result.done] == ["CSCI 151"]
    assert [c.code for c in result.missing] == ["CSCI 152"]


def test_course_below_minimum_grade_does_not_close_the_position():
    result = audit(
        program(courses=[course("CSCI 151", min_grade="C-")]),
        student(done("CSCI 151", grade=1.0)),
    )
    assert not result.done
    assert result.low_grade[0][0].code == "CSCI 151"
    assert result.low_grade[0][1] == 1.0
    assert not result.is_complete


def test_course_without_a_grade_counts_as_in_progress():
    result = audit(
        program(courses=[course("CSCI 299")]),
        student(CompletedCourse("CSCI 299", None, 7, credits=6)),
    )
    assert not result.done
    assert [c.code for c in result.in_progress] == ["CSCI 299"]
    # незачтённый курс не приносит кредитов
    assert result.earned_credits == 0


def test_narrow_positions_are_filled_before_wide_ones():
    # BIOL 101 закрывает и естественнонаучную позицию, и открытую, но
    # открытую закрыть больше нечем, а естественнонаучную — только им
    result = audit(
        program(
            slots=[
                slot("Open Elective", kind="general"),
                slot("Natural Science Elective", kind="natural science", codes=["BIOL 101"]),
            ]
        ),
        student(done("BIOL 101"), done("HST 200")),
    )
    closed = {s.slot.name: s.closed_by for s in result.slots}
    assert closed["Natural Science Elective"] == "BIOL 101"
    assert closed["Open Elective"] == "HST 200"
    assert not result.extra


def test_position_without_a_known_list_stays_unchecked():
    result = audit(
        program(slots=[slot("Kazakh Language")]),
        student(done("KAZ 313")),
    )
    status = result.slots[0]
    assert not status.is_closed
    assert not status.is_checkable
    assert result.unchecked_slots == [status]
    # курс не приписан наугад, он виден как лишний
    assert [c.code for c in result.extra] == ["KAZ 313"]


def test_open_position_is_checkable_even_without_a_list():
    result = audit(program(slots=[slot("Open Elective", kind="general")]), student())
    assert result.slots[0].is_checkable
    assert not result.slots[0].is_closed


def test_extra_courses_are_not_hidden():
    result = audit(program(courses=[course("CSCI 151")]), student(done("CSCI 151"), done("ANT 101")))
    assert [c.code for c in result.extra] == ["ANT 101"]


def test_credits_come_from_the_transcript_not_from_the_plan():
    result = audit(
        program(courses=[course("CSCI 151", credits=8)], total=240),
        student(done("CSCI 151", credits=8), done("ANT 101", credits=6)),
    )
    assert result.earned_credits == 14
    assert result.remaining_credits == 226


def test_failed_course_earns_nothing():
    result = audit(program(courses=[course("CSCI 151")]), student(done("CSCI 151", grade=0.0)))
    assert result.earned_credits == 0
    assert result.low_grade or result.done


def test_degree_credits_fall_back_to_the_plan():
    result = audit(program(courses=[course("CSCI 151", credits=8)], slots=[slot("Elective")]), student())
    assert result.degree_credits == 14


def test_programme_is_complete_when_nothing_is_left():
    result = audit(
        program(courses=[course("CSCI 151")], slots=[slot("Technical Elective", kind="technical", codes=["CSCI 434"])]),
        student(done("CSCI 151"), done("CSCI 434")),
    )
    assert result.is_complete


def test_remaining_by_kind_counts_open_positions_as_electives():
    result = audit(
        program(
            courses=[course("CSCI 151", kind=CourseKind.MAJOR, credits=8)],
            slots=[slot("Technical Elective", kind="technical", codes=["CSCI 434"])],
        ),
        student(),
    )
    assert remaining_by_kind(result) == {CourseKind.MAJOR: 8, CourseKind.ELECTIVE: 6}


def test_empty_audit_has_no_credits():
    assert Audit(program=program(), student=student()).earned_credits == 0
