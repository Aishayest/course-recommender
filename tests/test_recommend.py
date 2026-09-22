from datetime import time

from course_recommender.conditions import All, CourseNeeded
from course_recommender.data.assemble import PlanSlot, Program
from course_recommender.data.schedule import CourseHistory, Meeting, Section
from course_recommender.domain import CompletedCourse, Course, CourseKind, Requirement, Student
from course_recommender.recommend import Evidence, _conflicts, _fallback, recommend, utility

NO_PREREQUISITES = All(())


def course(code="CSCI 341", kind=CourseKind.MAJOR, semester=3, requirement=NO_PREREQUISITES):
    return Course(code, code, 6, kind, requirement=requirement, recommended_semester=semester)


def evidence(**kwargs) -> Evidence:
    return Evidence(course=kwargs.pop("course", course()), **kwargs)


def section(code, label="1L", days=("M",), start=time(9, 0), end=time(9, 50)):
    return Section(
        term="Fall 2026",
        code=code,
        section=label,
        meetings=[Meeting(days, start, end)],
    )


def test_fills_up_falls_back_to_mean_fill_without_a_model():
    # Правило без модели умеет только "да" или "нет" — за этим её и заводят
    assert evidence(mean_fill=1.2).fills_up == 1.0
    assert evidence(mean_fill=0.8).fills_up == 0.0
    assert evidence(mean_fill=None).fills_up == 0.5


def test_model_outranks_the_rule_when_it_is_there():
    assert evidence(fill_chance=0.3, mean_fill=1.2).fills_up == 0.3


def test_priority_matters_only_when_the_course_fills_up():
    crowded = {"fill_chance": 1.0}
    assert evidence(priority_tier=1, **crowded).seat_chance == 0.85
    assert evidence(priority_tier=None, **crowded).seat_chance == 0.05

    # Если курс не заполняется, тир не важен: мест хватает всем
    spare = {"fill_chance": 0.0}
    assert evidence(priority_tier=None, **spare).seat_chance == 0.99
    assert evidence(priority_tier=4, **spare).seat_chance == 0.99


def test_seat_chance_grows_with_priority():
    crowded = {"fill_chance": 0.8}
    chances = [evidence(priority_tier=tier, **crowded).seat_chance for tier in (1, 2, 3, 4)]
    assert chances == sorted(chances, reverse=True)


def test_unknown_history_gives_middle_estimate():
    # Ни истории, ни модели: половина вероятности на то, что курс заполнится
    assert evidence(mean_fill=None, priority_tier=None).seat_chance == 0.525


def test_seat_chance_never_claims_certainty():
    assert evidence(fill_chance=0.0, priority_tier=1).seat_chance == 0.99


def test_seat_chance_separates_courses_of_the_same_tier():
    # Ради этого и заводили модель: внутри одного тира курсы должны различаться
    likely = evidence(fill_chance=0.9, priority_tier=1).seat_chance
    unlikely = evidence(fill_chance=0.2, priority_tier=1).seat_chance
    assert unlikely > likely


def test_need_prefers_course_standing_in_plan():
    on_plan = evidence(on_plan=True)
    covering = evidence(covers=CourseKind.CORE)
    other = evidence(course=course(kind=CourseKind.ELECTIVE))
    assert on_plan.need > covering.need > other.need


def test_utility_combines_need_and_access():
    assert utility(1.0, 1.0) == 1.0
    assert utility(1.0, 0.0) > utility(0.0, 1.0)  # нужность весит больше


def test_courses_compatible_when_another_section_fits():
    # у каждого курса две лекции в разное время — сочетание без пересечения есть
    sections = {
        "A 101": [section("A 101", "1L"), section("A 101", "2L", start=time(11, 0), end=time(11, 50))],
        "B 101": [section("B 101", "1L"), section("B 101", "2L", start=time(13, 0), end=time(13, 50))],
    }
    assert _conflicts("A 101", ["B 101"], sections) == ()


def test_courses_conflict_when_every_pair_overlaps():
    sections = {"A 101": [section("A 101")], "B 101": [section("B 101")]}
    assert _conflicts("A 101", ["B 101"], sections) == ("B 101",)


def test_conflicts_ignore_courses_without_schedule():
    assert _conflicts("A 101", ["B 101"], {"A 101": [section("A 101")]}) == ()


def test_fallback_offers_easier_course_of_same_kind():
    hard = evidence(course=course("CSCI 494"), fill_chance=0.9, priority_tier=None)
    easy = evidence(course=course("CSCI 341"), fill_chance=0.2, priority_tier=None)
    other_kind = evidence(course=course("HST 100", kind=CourseKind.CORE), fill_chance=0.0)
    assert _fallback(hard, [hard, easy, other_kind]) is easy.course
    assert _fallback(easy, [hard, easy]) is None


def make_program(*courses: Course) -> Program:
    return Program(
        admission_year=2026,
        name="COMPUTER SCIENCE (CS)",
        degree="BSc",
        courses={c.code: c for c in courses},
        requirements=[Requirement(CourseKind.MAJOR, required_credits=60)],
    )


def test_recommend_ranks_crowded_course_below_reachable_one():
    program = make_program(
        course("CSCI 341", semester=3),
        course("CSCI 494", semester=3),
    )
    student = Student("s1", "COMPUTER SCIENCE (CS)", 2, 3.0, [])
    result = recommend(
        program,
        student,
        semester=3,
        fill_history={
            "CSCI 341": CourseHistory("CSCI 341", "", (("Fall 2025", 0.5),)),
            "CSCI 494": CourseHistory("CSCI 494", "", (("Fall 2025", 1.58),)),
        },
    )
    assert [r.course.code for r in result] == ["CSCI 341", "CSCI 494"]
    assert result[1].fallback is not None


def test_recommend_skips_completed_and_unmet_courses():
    program = make_program(
        course("CSCI 341", requirement=CourseNeeded("CSCI 152", min_grade="C-")),
        course("CSCI 231", requirement=NO_PREREQUISITES),
    )
    student = Student(
        "s1", "COMPUTER SCIENCE (CS)", 2, 3.0, [CompletedCourse("CSCI 231", 3.0, 1)]
    )
    codes = [r.course.code for r in recommend(program, student, semester=3)]
    assert codes == []  # CSCI 231 уже пройден, на CSCI 341 не хватает пререквизита


def test_recommend_explains_itself():
    program = make_program(course("CSCI 231", semester=3))
    student = Student("s1", "COMPUTER SCIENCE (CS)", 2, 3.0, [])
    (result,) = recommend(
        program,
        student,
        semester=3,
        fill_history={"CSCI 231": CourseHistory("CSCI 231", "", (("Fall 2025", 0.9),))},
    )
    assert "стоит в плане" in result.why
    assert "90%" in result.why


def test_need_prefers_course_closing_an_open_plan_position():
    # Позицию "Technical Elective" всё равно чем-то закрывать придётся,
    # поэтому закрывающий её курс нужнее произвольного профильного.
    fills = evidence(fills_slot="Technical Elective")
    covering = evidence(covers=CourseKind.MAJOR)
    assert evidence(on_plan=True).need > fills.need > covering.need


def test_recommend_offers_elective_for_open_plan_position():
    program = make_program(course("CSCI 408", semester=7))
    program.slots = [
        PlanSlot(
            name="Technical Elective",
            semester=7,
            term="fall",
            credits=6,
            kind="technical",
            eligible_codes=frozenset({"CSCI 434"}),
        )
    ]
    program.courses["CSCI 434"] = Course(
        "CSCI 434", "Information Security", 6, CourseKind.ELECTIVE, requirement=NO_PREREQUISITES
    )
    student = Student("s1", "COMPUTER SCIENCE (CS)", 4, 3.0, [])

    results = {r.course.code: r for r in recommend(program, student, semester=7)}
    assert set(results) == {"CSCI 408", "CSCI 434"}
    assert "закрывает позицию плана «Technical Elective»" in results["CSCI 434"].why
