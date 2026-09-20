from course_recommender.data.canva import Block, Page, Table
from course_recommender.data.handbook import (
    GRADE_POINTS,
    is_continuation,
    is_plan_table,
    normalize,
    parse_course_cell,
    parse_credits,
    parse_grade,
    parse_plans,
    parse_program_heading,
    split_alternatives,
)


def test_normalize_fixes_cyrillic_homoglyph():
    # в handbook встречается кириллическая С вместо латинской
    assert normalize("С-") == "C-"
    assert normalize("С-") in GRADE_POINTS


def test_normalize_collapses_whitespace():
    assert normalize("BSc in  Computer\nScience") == "BSc in Computer Science"


def test_parse_grade_plain():
    assert parse_grade("C-") == ("C-", "")


def test_parse_grade_with_footnote_marker():
    assert parse_grade("C-**") == ("C-", "**")
    assert parse_grade("D***") == ("D", "***")


def test_parse_grade_cyrillic():
    assert parse_grade("С-") == ("C-", "")


def test_parse_grade_empty():
    assert parse_grade("") == (None, "")


def test_parse_credits_single_and_range():
    assert parse_credits("6") == (6,)
    assert parse_credits("6 or 8") == (6, 8)
    assert parse_credits("") == ()


def test_parse_course_cell_code_and_title():
    (ref,) = parse_course_cell("BUS 101 Core Course in Business")
    assert ref.code == "BUS 101"
    assert ref.title == "Core Course in Business"


def test_parse_course_cell_handles_colon():
    (ref,) = parse_course_cell("PHIL 210 : Ethics")
    assert ref.code == "PHIL 210"
    assert ref.title == "Ethics"


def test_parse_course_cell_alternatives():
    refs = parse_course_cell("MATH 109: Mathematical Discovery or MATH 161: Calculus I")
    assert [r.code for r in refs] == ["MATH 109", "MATH 161"]


def test_parse_course_cell_placeholder_without_code():
    (ref,) = parse_course_cell("Kazakh Language")
    assert ref.is_placeholder
    assert ref.title == "Kazakh Language"


def test_parse_course_cell_strips_footnote_marker():
    (ref,) = parse_course_cell("Natural Science Elective*")
    assert ref.title == "Natural Science Elective"


def test_parse_course_cell_skips_total_row():
    assert parse_course_cell("Total semester ECTS credits") == []


def test_split_keeps_parentheses_intact():
    assert split_alternatives("CSCI course (e.g. CSCI 115 or CSCI 151)") == [
        "CSCI course (e.g. CSCI 115 or CSCI 151)"
    ]


def test_split_separates_top_level_alternatives():
    parts = split_alternatives("Major Elective 3 (BIOL 456) or Honors Thesis (BIOL 490)")
    assert len(parts) == 2


def test_continuation_row_detected():
    assert is_continuation("or HST 100 History of Kazakhstan")
    assert not is_continuation("HST 100 History of Kazakhstan")


def test_program_heading_normalized():
    assert parse_program_heading("BSc in  Computer Science") == ("BSc", "COMPUTER SCIENCE")
    assert parse_program_heading("BS IN NURSING") == ("BSc", "NURSING")
    assert parse_program_heading("BBA of Business Administration") == (
        "BBA",
        "BUSINESS ADMINISTRATION",
    )


def test_program_heading_rejects_other_text():
    assert parse_program_heading("YEAR 1") is None


def test_is_plan_table_accepts_plan_header():
    table = Table(
        rows=[["Fall", "minimum required grade", "ECTS", "Spring", "minimum required grade", "ECTS"]]
    )
    assert is_plan_table(table)


def test_is_plan_table_rejects_calendar():
    assert not is_plan_table(Table(rows=[["Fall semester 2025", ""]]))


def _plan_table(first_course: str) -> Table:
    return Table(
        rows=[
            ["Fall", "minimum required grade", "ECTS", "Spring", "minimum required grade", "ECTS"],
            [first_course, "C-", "6", "BUS 102 Second", "D", "6"],
        ]
    )


def _grid_page() -> Page:
    """Страница с четырьмя планами сеткой 2x2, как в handbook."""
    return Page(
        number=1,
        blocks=[
            Block("text", top=9.7, left=49.3, width=400, height=20, text="BBA in BUSINESS"),
            Block("text", top=53.1, left=232.5, width=40, height=15, text="YEAR 1"),
            Block("text", top=53.1, left=761.9, width=40, height=15, text="YEAR 3"),
            Block("table", top=71.2, left=49.3, width=500, height=300, table=_plan_table("BUS 101 First")),
            Block("table", top=71.2, left=577.0, width=500, height=300, table=_plan_table("FIN 201 Second")),
            Block("text", top=379.4, left=236.2, width=40, height=15, text="YEAR 2"),
            Block("text", top=379.4, left=765.5, width=40, height=15, text="YEAR 4"),
            Block("table", top=396.9, left=49.3, width=500, height=300, table=_plan_table("MGT 301 Third")),
            Block("table", top=396.9, left=577.0, width=500, height=300, table=_plan_table("ACCT 401 Fourth")),
        ],
    )


def test_grid_layout_assigns_each_plan_its_own_year():
    entries = parse_plans([_grid_page()], admission_year=2026)
    fall = {e.options[0].code: e.study_year for e in entries if e.term == "fall"}
    assert fall == {"BUS 101": 1, "FIN 201": 3, "MGT 301": 2, "ACCT 401": 4}


def test_plan_row_yields_both_terms():
    entries = parse_plans([_grid_page()], admission_year=2026)
    assert {e.term for e in entries} == {"fall", "spring"}
    assert all(e.program == "BUSINESS" for e in entries)
