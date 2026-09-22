from course_recommender.conditions import course_codes, evaluate
from course_recommender.data.registration import parse_expression
from course_recommender.domain import CompletedCourse, Student


def student(*graded: tuple[str, float]) -> Student:
    return Student(
        "s1",
        major="Computer Science",
        year=2,
        gpa=3.0,
        completed=[CompletedCourse(code, grade, 1) for code, grade in graded],
    )


def test_evaluate_grade_threshold():
    node = parse_expression("ECON 101 Intro (379) (B- and above)")
    assert evaluate(node, student(("ECON 101", 2.67))) is True
    assert evaluate(node, student(("ECON 101", 1.67))) is False
    assert evaluate(node, student()) is False


def test_evaluate_any_and_all():
    node = parse_expression(
        "AAA 101 A (1) (C and above) AND (BBB 102 B (2) (C and above) OR CCC 103 C (3) (C and above))"
    )
    assert evaluate(node, student(("AAA 101", 3.0), ("CCC 103", 2.0))) is True
    assert evaluate(node, student(("AAA 101", 3.0))) is False


def test_unknown_test_score_stays_unknown():
    # ASC 200 допускает вход по IELTS, которого в транскрипте нет
    node = parse_expression(
        'ASC 100 English (9234) (C- and above) OR Test "IELTS" BETWEEN 6.5 and 9'
    )
    assert evaluate(node, student()) is None
    assert evaluate(node, student(("ASC 100", 2.0))) is True
    assert evaluate(node, student(), known_tests={"IELTS": 7.0}) is True
    assert evaluate(node, student(), known_tests={"IELTS": 5.0}) is False


def test_unknown_inside_and_does_not_hide_failure():
    node = parse_expression('AAA 101 A (1) (C and above) AND KLL "[C1.1] Advanced"')
    assert evaluate(node, student()) is False  # курса нет — точно не выполнено
    assert evaluate(node, student(("AAA 101", 3.0))) is None  # остаётся неизвестное


def test_evaluate_subject_range():
    node = parse_expression('Subject "HST" BETWEEN 200 and 299')
    assert evaluate(node, student(("HST 243", 3.0))) is True
    assert evaluate(node, student(("HST 100", 3.0))) is False


def test_course_codes_collects_dependencies():
    node = parse_expression(
        "ECON 101 A (1) (C and above) AND (MATH 161 B (2) (C and above) OR MATH 162 C (3) (C and above))"
    )
    assert course_codes(node) == {"ECON 101", "MATH 161", "MATH 162"}
