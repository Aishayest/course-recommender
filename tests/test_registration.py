from course_recommender.conditions import All, Any, CourseNeeded, ExamScore, Placement, SubjectRange
from course_recommender.data.registration import (
    Audience,
    CourseOffering,
    is_section_header,
    parse_audiences,
    parse_expression,
    parse_row,
)


def test_single_course_with_grade():
    node = parse_expression("CSCI 151 Programming for Scientists and Engineers (192) (C- and above)")
    assert node == CourseNeeded("CSCI 151", "Programming for Scientists and Engineers", "192", "C-")


def test_pass_and_fail_outcomes():
    passed = parse_expression("ECON 300 Research Assistance in Economics (3080) (P)")
    assert passed.outcome == "P"
    failed = parse_expression("CSCI 151 Programming (192) (F)")
    assert failed.outcome == "F"


def test_missing_grade_is_none():
    node = parse_expression("SMG 100 Introduction to Natural Resources Extraction (4773) ( and above)")
    assert node.min_grade is None and node.outcome is None


def test_and_binds_tighter_than_or():
    # A OR B AND C читается как A OR (B AND C)
    node = parse_expression(
        "AAA 101 First (1) (C and above) OR BBB 102 Second (2) (C and above) "
        "AND CCC 103 Third (3) (C and above)"
    )
    assert isinstance(node, Any)
    assert isinstance(node.terms[1], All)


def test_parentheses_override_precedence():
    node = parse_expression(
        "ECON 101 Introduction to Microeconomics (379) (B- and above) AND "
        "(MATH 161 Calculus I (118) (B- and above) OR MATH 162 Calculus II (170) (B- and above))"
    )
    assert isinstance(node, All)
    assert isinstance(node.terms[1], Any)
    assert [t.code for t in node.terms[1].terms] == ["MATH 161", "MATH 162"]


def test_nested_expression_keeps_structure():
    node = parse_expression(
        "ECON 211 Economic Statistics (2280) (C- and above) OR (MATH 321 Probability (482) "
        "(C- and above) AND (MATH 322 Mathematical Statistics (1165) (C- and above) OR "
        "MATH 310 Applied Statistical Methods (82) (C- and above)))"
    )
    assert str(node) == "(ECON 211 ≥ C- OR (MATH 321 ≥ C- AND (MATH 322 ≥ C- OR MATH 310 ≥ C-)))"


def test_slashed_course_code():
    node = parse_expression("HST 274/WLL 274 Texts and Contexts (5701) (C- and above)")
    assert node.code == "HST 274/WLL 274"


def test_title_with_parentheses_does_not_break_atom():
    node = parse_expression(
        "ENG 200 Engineering Mathematics III (Differential Equations and Linear Algebra) "
        "(5009) (C- and above)"
    )
    assert node.code == "ENG 200"
    assert node.catalog_id == "5009"


def test_subject_range_atom():
    assert parse_expression('Subject "HST" BETWEEN 200 and 299') == SubjectRange("HST", 200, 299)


def test_test_score_atom():
    assert parse_expression('Test "IELTS" BETWEEN 6.5 and 9') == ExamScore("IELTS", 6.5, 9.0)


def test_placement_atom():
    node = parse_expression('KLL "[C1.1] Advanced"')
    assert isinstance(node, Placement) and node.level == "C1.1"


def test_empty_expression_is_none():
    assert parse_expression("") is None


def test_parse_audiences_structured():
    audiences, permission = parse_audiences("3 year UG SSH Sociology, Economics, SCAI")
    assert not permission
    assert (audiences[0].year, audiences[0].school, audiences[0].program) == (3, "SSH", "Sociology")
    assert (audiences[1].year, audiences[1].school, audiences[1].program) == (None, None, "Economics")
    assert (audiences[2].year, audiences[2].school, audiences[2].program) == (None, "SCAI", None)


def test_parse_audiences_permission_flag():
    audiences, permission = parse_audiences(
        "Instructor's Permission Required. Registration through Add Course form only!"
    )
    assert permission and audiences == []


def test_pending_graduation_marked():
    audiences, _ = parse_audiences("5 year UG SoE (pending graduation)")
    assert audiences[0].pending_graduation


def test_audience_matching_rules():
    assert Audience(year=3, school="SSH", program="Sociology").matches(3, "SSH", "Sociology")
    assert not Audience(year=3, school="SSH", program="Sociology").matches(2, "SSH", "Sociology")
    # пустое поле означает "любой"
    assert Audience(school="SCAI").matches(1, "SCAI", "Computer Science")
    assert Audience(program="Economics").matches(4, "GSB", "economics")


def test_program_suffix_ignored_when_matching():
    assert Audience(program="Business Administration (UG)").matches(1, "GSB", "Business Administration")


def test_priority_tier_lookup():
    offering = CourseOffering(
        term="Fall 2026",
        school="SCAI",
        department="Computer Science",
        code="CSCI 341",
        title="Database Systems",
        priorities=[
            [Audience(year=3, school="SCAI", program="Computer Science")],
            [Audience(school="SCAI")],
        ],
    )
    assert offering.priority_for(3, "SCAI", "Computer Science") == 1
    assert offering.priority_for(2, "SCAI", "Computer Science") == 2
    assert offering.priority_for(2, "SSH", "Sociology") is None


def test_section_header_detection():
    assert is_section_header(["GSB"] + [""] * 11)
    assert not is_section_header(["1", "BBA 208", "Data Analytics", "3", "6"] + [""] * 7)


def test_parse_row_builds_offering():
    row = [
        "11",
        "ECON 201",
        "Intermediate Microeconomics",
        "3",
        "6",
        "ECON 101 Intro (379) (B- and above)",
        "",
        "",
        "Business Administration (UG), Economics",
        "Mathematics",
        "",
        "",
    ]
    offering = parse_row(row, "Fall 2026", "GSB", "Economics")
    assert offering.code == "ECON 201"
    assert offering.credits_ects == 6
    assert offering.prerequisite.code == "ECON 101"
    assert len(offering.priorities) == 2  # пустые хвостовые тиры отброшены
    assert offering.priority_for(2, "GSB", "Economics") == 1
