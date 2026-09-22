from course_recommender.conditions import All, CourseNeeded, ExamScore
from course_recommender.constraints import (
    eligible_courses,
    is_eligible,
    prerequisites_met,
    remaining_requirements,
)
from course_recommender.domain import (
    CompletedCourse,
    Course,
    CourseKind,
    Requirement,
    Student,
)

MATH101 = Course("MATH101", "Calculus I", 3, CourseKind.CORE)
CS102 = Course("CS102", "Programming I", 3, CourseKind.CORE)
CS201 = Course(
    "CS201",
    "Data Structures",
    3,
    CourseKind.MAJOR,
    prerequisites=[["CS102"]],
)
ML301 = Course(
    "ML301",
    "Machine Learning",
    4,
    CourseKind.MAJOR,
    prerequisites=[["MATH101"], ["CS201", "CS202"]],
    semesters_offered=(1,),
)

CATALOG = [MATH101, CS102, CS201, ML301]


def make_student(*codes: str) -> Student:
    completed = [CompletedCourse(code, 3.5, 1) for code in codes]
    return Student("s1", "CS", year=2, gpa=3.5, completed=completed)


def test_no_prerequisites_always_met():
    assert prerequisites_met(MATH101, make_student())


def test_prerequisites_missing():
    assert not prerequisites_met(CS201, make_student())


def test_prerequisites_satisfied():
    assert prerequisites_met(CS201, make_student("CS102"))


def test_or_group_satisfied_by_either_option():
    assert prerequisites_met(ML301, make_student("MATH101", "CS201"))
    assert prerequisites_met(ML301, make_student("MATH101", "CS202"))


def test_and_group_requires_all():
    assert not prerequisites_met(ML301, make_student("CS201"))


def test_completed_course_not_eligible():
    assert not is_eligible(MATH101, make_student("MATH101"), semester=1)


def test_course_not_offered_this_semester():
    student = make_student("MATH101", "CS201")
    assert is_eligible(ML301, student, semester=1)
    assert not is_eligible(ML301, student, semester=2)


def test_eligible_courses_filters_catalog():
    result = eligible_courses(CATALOG, make_student("CS102"), semester=1)
    assert {c.code for c in result} == {"MATH101", "CS201"}


def test_remaining_requirements_counts_earned_credits():
    catalog = {c.code: c for c in CATALOG}
    student = make_student("MATH101", "CS102")
    requirements = [
        Requirement(CourseKind.CORE, required_credits=9),
        Requirement(CourseKind.MAJOR, required_credits=6),
    ]
    remaining = remaining_requirements(requirements, catalog, student)
    assert remaining == {CourseKind.CORE: 3, CourseKind.MAJOR: 6}


def test_satisfied_requirement_is_dropped():
    catalog = {c.code: c for c in CATALOG}
    student = make_student("MATH101", "CS102")
    requirements = [Requirement(CourseKind.CORE, required_credits=6)]
    assert remaining_requirements(requirements, catalog, student) == {}


ECON101 = Course("ECON101", "Microeconomics", 6, CourseKind.CORE)
ECON201 = Course(
    "ECON201",
    "Intermediate Micro",
    6,
    CourseKind.MAJOR,
    prerequisites=[["ECON101"]],
    # handbook: ECON 101 сдаётся на C-, но как пререквизит требует B-
    prerequisite_min_grades={"ECON101": "B-"},
)


def student_with(code: str, grade: float) -> Student:
    return Student("s2", "ECON", year=2, gpa=grade, completed=[CompletedCourse(code, grade, 1)])


def test_prerequisite_grade_too_low():
    assert not prerequisites_met(ECON201, student_with("ECON101", 1.67))  # C-


def test_prerequisite_grade_exactly_at_threshold():
    assert prerequisites_met(ECON201, student_with("ECON101", 2.67))  # B-


def test_prerequisite_grade_above_threshold():
    assert prerequisites_met(ECON201, student_with("ECON101", 4.0))  # A


def test_prerequisite_without_min_grade_accepts_any_pass():
    assert prerequisites_met(CS201, student_with("CS102", 1.0))  # D


def test_grade_of_returns_none_for_unknown_course():
    assert student_with("CS102", 3.0).grade_of("MATH101") is None


def test_respect_plan_hides_courses_scheduled_later():
    early = Course("CS100", "Intro", 6, CourseKind.MAJOR, recommended_semester=1)
    late = Course("CS400", "Senior Project", 6, CourseKind.MAJOR, recommended_semester=7)
    student = make_student()
    assert {c.code for c in eligible_courses([early, late], student, 3)} == {"CS100", "CS400"}
    assert {c.code for c in eligible_courses([early, late], student, 3, respect_plan=True)} == {
        "CS100"
    }


def test_respect_plan_keeps_courses_without_plan_position():
    floating = Course("CS150", "Elective", 6, CourseKind.ELECTIVE)
    result = eligible_courses([floating], make_student(), 3, respect_plan=True)
    assert [c.code for c in result] == ["CS150"]


def requirement_course(code: str, requirement, semester: int | None = None) -> Course:
    return Course(code, "", 6, CourseKind.MAJOR, requirement=requirement, recommended_semester=semester)


def test_requirement_replaces_handbook_prerequisites():
    course = requirement_course("CS300", CourseNeeded("CS200", min_grade="C"))
    assert prerequisites_met(course, student_with("CS200", 2.0))
    assert not prerequisites_met(course, student_with("CS200", 1.67))


def test_requirement_wins_over_legacy_fields():
    # если настоящее условие известно, приближение из handbook не используется
    course = Course(
        "CS300",
        "",
        6,
        CourseKind.MAJOR,
        prerequisites=[["NEVER"]],
        requirement=CourseNeeded("CS200", min_grade="C"),
    )
    assert prerequisites_met(course, student_with("CS200", 3.0))


def test_empty_requirement_means_no_prerequisites():
    assert prerequisites_met(requirement_course("CS100", All(())), make_student())


def test_unknown_condition_allowed_by_default():
    course = requirement_course("ASC200", ExamScore("IELTS", 6.5, 9.0))
    assert prerequisites_met(course, make_student())
    assert not prerequisites_met(course, make_student(), allow_unknown=False)


def test_known_test_score_resolves_unknown():
    course = requirement_course("ASC200", ExamScore("IELTS", 6.5, 9.0))
    assert prerequisites_met(course, make_student(), known_tests={"IELTS": 7.0})
    assert not prerequisites_met(course, make_student(), known_tests={"IELTS": 5.0})


def test_plan_fallback_skipped_when_requirement_known():
    # курс из плана позже текущего семестра, но условие выполнено -> идём с опережением
    late = requirement_course("CS400", All(()), semester=7)
    result = eligible_courses([late], make_student(), 3, respect_plan=True)
    assert [c.code for c in result] == ["CS400"]


def test_plan_fallback_still_guards_courses_without_data():
    late = Course("CS400", "", 6, CourseKind.MAJOR, recommended_semester=7)
    assert eligible_courses([late], make_student(), 3, respect_plan=True) == []
    assert [c.code for c in eligible_courses([late], make_student(), 3)] == ["CS400"]
