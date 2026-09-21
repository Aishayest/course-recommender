from course_recommender.data.canva import Block, Page, Table
from course_recommender.data.requirements import (
    degree_credits,
    expand_codes,
    is_requirement_table,
    parse_choices,
    parse_count,
    parse_min_grade,
    parse_min_level,
    parse_requirement_table,
    parse_requirements,
    to_requirements,
)
from course_recommender.domain import CourseKind


def test_expand_codes_plain():
    assert expand_codes("ECON 101 Introduction to Microeconomics") == ["ECON 101"]


def test_expand_codes_inherits_prefix_from_previous():
    # "PHIL 210, 211 or 212" — у второго и третьего номера префикс опущен
    assert expand_codes("One Ethics course (PHIL 210, 211 or 212)") == [
        "PHIL 210",
        "PHIL 211",
        "PHIL 212",
    ]


def test_expand_codes_without_prefix_yields_nothing():
    assert expand_codes("Two courses at 100-level") == []


def test_parse_count_from_word():
    assert parse_count("Any four ANT electives at 200-level or above") == 4
    assert parse_count("Two KAZ courses") == 2
    assert parse_count("Electives") is None


def test_parse_min_level():
    assert parse_min_level("Any four ANT electives at 200-level or above") == 200
    assert parse_min_level("Three 400-level Economics electives") == 400
    assert parse_min_level("One CSCI course") is None


def test_parse_min_grade_handles_spaced_quoted_form():
    # в handbook написано: passed with "C -" or better
    note = 'All major related courses should be passed with "C -" or better unless otherwise stated'
    assert parse_min_grade(note) == "C-"


def test_parse_min_grade_absent():
    assert parse_min_grade("Four Non-major Humanities electives") is None


def test_parse_choices_from_parentheses():
    assert parse_choices("One Ethics course (PHIL 210, 211 or 212)") == [
        ["PHIL 210", "PHIL 211", "PHIL 212"]
    ]


def test_parse_choices_from_choice_of():
    groups = parse_choices("Required: ANT 101 Choice of: ANT 110, ANT 140, ANT 160, or ANT 175")
    assert ["ANT 110", "ANT 140", "ANT 160", "ANT 175"] in groups


def test_is_requirement_table_accepts_header():
    assert is_requirement_table(
        Table(rows=[["Anthropology requirements", "Credits", "Explanation"]])
    )
    assert is_requirement_table(Table(rows=[["MAJOR requirements", "Credits"]]))


def test_is_requirement_table_rejects_plan_and_others():
    assert not is_requirement_table(
        Table(
            rows=[
                [
                    "Fall",
                    "minimum required grade",
                    "ECTS",
                    "Spring",
                    "minimum required grade",
                    "ECTS",
                ]
            ]
        )
    )
    assert not is_requirement_table(Table(rows=[["No", "Course Title", "Credits"]]))


def _requirements_table() -> Table:
    return Table(
        rows=[
            ["Anthropology requirements", "Credits", "Explanation"],
            ["Elementary Courses", "12", "Required: ANT 101 Choice of: ANT 110, ANT 140"],
            ["Intermediate/Advanced Electives", "24", "Any four ANT electives at 200-level"],
            ["Total Major Credits", "72", 'All major courses passed with "C -" or better'],
            ["Core requirements", "Credits", "Explanation"],
            ["Ethics", "6", "One Ethics course (PHIL 210, 211 or 212)"],
            ["Electives", "66", "Any courses from SSH, SEDS, SMG or SOM"],
            ["Total Degree Credits", "240", ""],
        ]
    )


def test_nested_core_section_switches_section():
    rows = parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")
    sections = {row.name: row.section for row in rows}
    assert sections["Elementary Courses"] == "major"
    assert sections["Ethics"] == "core"
    assert "Core requirements" not in sections  # строка-заголовок не становится требованием


def test_rows_capture_credits_and_rules():
    rows = {r.name: r for r in parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")}
    elementary = rows["Elementary Courses"]
    assert elementary.credits == 12
    assert "ANT 101" in [c.code for c in elementary.courses]
    advanced = rows["Intermediate/Advanced Electives"]
    assert (advanced.count, advanced.min_level) == (4, 200)
    assert rows["Total Major Credits"].min_grade == "C-"


def test_total_rows_flagged():
    rows = parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")
    assert [r.name for r in rows if r.is_total] == ["Total Major Credits", "Total Degree Credits"]


def test_elective_rows_mapped_to_elective_kind():
    rows = {r.name: r for r in parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")}
    assert rows["Electives"].kind is CourseKind.ELECTIVE
    assert rows["Elementary Courses"].kind is CourseKind.MAJOR
    assert rows["Ethics"].kind is CourseKind.CORE


def test_degree_credits_read_from_total_row():
    rows = parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")
    assert degree_credits(rows) == 240


def test_to_requirements_drops_totals():
    rows = parse_requirement_table(_requirements_table(), 2023, "ANTHROPOLOGY")
    requirements = to_requirements(rows)
    assert len(requirements) == 4  # четыре содержательные строки, обе Total отброшены
    assert sum(r.required_credits for r in requirements) == 12 + 24 + 6 + 66


def test_parse_requirements_uses_program_heading():
    page = Page(
        number=1,
        blocks=[
            Block("text", top=10, left=10, width=300, height=20, text="BA in ANTHROPOLOGY"),
            Block("table", top=50, left=10, width=500, height=400, table=_requirements_table()),
        ],
    )
    rows = parse_requirements([page], 2023)
    assert rows and {r.program for r in rows} == {"ANTHROPOLOGY"}


def test_parse_requirements_ignores_tables_before_any_program():
    page = Page(
        number=1,
        blocks=[Block("table", top=50, left=10, width=500, height=400, table=_requirements_table())],
    )
    assert parse_requirements([page], 2023) == []
