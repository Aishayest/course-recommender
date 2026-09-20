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
