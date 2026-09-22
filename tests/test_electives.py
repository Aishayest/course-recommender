from course_recommender.data.canva import Block, Page, Table
from course_recommender.data.electives import (
    ElectiveGroup,
    ElectiveRule,
    groups_from_requirements,
    leading_kind,
    match_titles,
    parse_electives,
    parse_exclusions,
    parse_listing,
    parse_min_level,
    parse_page,
    parse_rule,
    program_of_heading,
    slot_kind,
)
from course_recommender.data.handbook import CourseRef
from course_recommender.data.requirements import RequirementRow

CS_RULE = (
    "Technical Electives for the BS CS degree can be satisfied by any non-required course "
    "at 200-level or above offered by the CS department, as well as the following courses "
    "offered by other departments:"
)
NATURAL_SCIENCE_RULE = (
    "Natural Science Electives are any courses offered by Physics, Chemistry, Biology and "
    "Geology at 100-level or above that are not designated for “non-science majors”."
)
ROBT_RULE = (
    "**Technical Electives are ROBT-coded courses in the list below. "
    "Any SoE or MATH courses with the consent of the advisor."
)


def text(value, top=0.0):
    return Block(kind="text", top=top, left=0.0, text=value)


def table(rows, top=0.0):
    return Block(kind="table", top=top, left=0.0, table=Table(rows=rows))


def row(name, credits=6, *, section="major", explanation="", codes=(), count=None, total=False):
    return RequirementRow(
        admission_year=2026,
        program="MATHEMATICS",
        section=section,
        name=name,
        credits=credits,
        explanation=explanation,
        courses=[CourseRef(code=code, title="") for code in codes],
        count=count,
        is_total=total,
    )


def test_slot_kind_reads_plan_position_names():
    assert slot_kind("Technical Elective 2") == "technical"
    assert slot_kind("Natural Science Elective") == "natural science"
    # У инженеров профильный электив назван кодом департамента, и страница
    # handbook для него озаглавлена "... ELECTIVE COURSES".
    assert slot_kind("ELCE Elective 3") == "major"
    assert slot_kind("Kazakh Language") is None


def test_leading_kind_ignores_word_from_middle_of_sentence():
    # Примечание ECE упоминает технические стажировки, но описывает
    # профильные элективы специальности.
    note = (
        "Students should choose at least 5 elective courses on the basis of primary and "
        "secondary areas. Students can account external technical internships."
    )
    assert leading_kind(note) is None
    assert leading_kind(ROBT_RULE) == "technical"
    assert leading_kind(NATURAL_SCIENCE_RULE) == "natural science"


def test_program_of_heading_strips_elective_tail():
    assert program_of_heading("Geology TECHNICAL ELECTIVES") == "GEOLOGY"
    assert program_of_heading("PHYSICS ELECTIVE COURSES") == "PHYSICS"
    assert (
        program_of_heading("COMPUTER SCIENCE TECHNICAL AND NATURAL SCIENCE ELECTIVES")
        == "COMPUTER SCIENCE"
    )


def test_parse_min_level_takes_the_lowest_named():
    # "300– or 400-level" открывает и третий курс тоже
    assert parse_min_level("Any Math 300– or 400-level courses") == 300
    assert parse_min_level("at 200-level or above") == 200
    assert parse_min_level("Any two courses from MATH 407, MATH 411") is None


def test_parse_rule_reads_subject_and_level():
    rule = parse_rule(CS_RULE)
    assert rule.subjects == ("CSCI",)
    assert rule.min_level == 200
    assert rule.exclude_required


def test_parse_rule_maps_department_names_to_subjects():
    rule = parse_rule(NATURAL_SCIENCE_RULE)
    assert rule.subjects == ("PHYS", "CHEM", "BIOL", "GEOL")
    assert rule.min_level == 100
    assert not rule.exclude_required


def test_parse_rule_defers_to_explicit_list():
    # "in the list below" — правила нет, есть перечень
    assert parse_rule("Technical Electives are ROBT-coded courses in the list below.") is None


def test_parse_rule_marks_advisor_consent():
    rule = parse_rule("Any SoE or MATH courses with the consent of the advisor.")
    assert rule.schools == ("SOE",)
    assert rule.subjects == ("MATH",)
    assert rule.advisor_consent


def test_parse_exclusions():
    assert parse_exclusions("Any HST courses (except HST 100)") == frozenset({"HST 100"})
    assert parse_exclusions("Any HST courses") == frozenset()


def test_rule_matches_respects_level_and_required():
    rule = ElectiveRule(subjects=("CSCI",), min_level=200, exclude_required=True)
    assert rule.matches("CSCI 341", required=frozenset())
    assert not rule.matches("CSCI 151", required=frozenset())
    assert not rule.matches("CSCI 341", required=frozenset({"CSCI 341"}))
    assert not rule.matches("MATH 322", required=frozenset())


def test_rule_matches_by_school_when_school_is_known():
    rule = ElectiveRule(schools=("SOE",))
    assert rule.matches("CEE 300", school="SoE")
    # Без данных о школе правило не срабатывает: гадать нельзя
    assert not rule.matches("CEE 300")


def test_parse_listing_numbered_table():
    courses, titles, areas = parse_listing(
        [
            ["No", "Course Title", "Credits"],
            ["1", "ROBT 305 Embedded Systems", "6"],
            ["2", "ROBT 307 Power Electronics", "6"],
            ["", "Total", "36"],
        ]
    )
    assert [c.code for c in courses] == ["ROBT 305", "ROBT 307"]
    assert courses[0].title == "Embedded Systems"
    assert not titles and not areas


def test_parse_listing_areas_table_keeps_columns_apart():
    courses, titles, areas = parse_listing(
        [
            ["Devices and Circuits", "Power Engineering"],
            ["Solid State Devices", "Electric Machines"],
            ["Analog Circuit Design", ""],
        ]
    )
    assert not courses
    assert areas["Devices and Circuits"] == ["Solid State Devices", "Analog Circuit Design"]
    assert areas["Power Engineering"] == ["Electric Machines"]
    assert set(titles) == {"Solid State Devices", "Analog Circuit Design", "Electric Machines"}


def test_parse_page_keeps_sections_apart():
    # Ниже списка элективов на той же странице идут требования к переводу
    # со своим списком CSCI-курсов: элективами они не являются.
    page = Page(
        number=39,
        blocks=[
            text("COMPUTER SCIENCE TECHNICAL AND NATURAL SCIENCE ELECTIVES", top=0),
            text("Technical electives", top=10),
            table([[CS_RULE]], top=20),
            table([["MATH 322 Mathematical Statistics"], ["ROBT 310 Image Processing"]], top=30),
            text("Transfer requirements", top=40),
            table([["CSCI 151 Programming for Scientists and Engineers"]], top=50),
        ],
    )
    groups = {group.kind: group for group in parse_page(page, 2026)}
    assert groups["technical"].program == "COMPUTER SCIENCE"
    assert groups["technical"].listed_codes == {"MATH 322", "ROBT 310"}
    assert groups["technical"].rules[0].subjects == ("CSCI",)


def test_parse_page_ignores_minor_list():
    page = Page(
        number=64,
        blocks=[
            text("Robotics Engineering Natural Science ELECTIVEs", top=0),
            table([[ROBT_RULE]], top=10),
            text("Minor in Robotics Engineering", top=20),
            table([["No", "Course Title", "Credits"], ["1", "ROBT 305 Embedded Systems", "6"]], top=30),
        ],
    )
    groups = {group.kind: group for group in parse_page(page, 2023)}
    assert groups["technical"].listed_codes == set()
    assert groups["technical"].rules[0].advisor_consent


def test_parse_electives_keys_by_program_and_kind():
    pages = [
        Page(
            number=39,
            blocks=[
                text("COMPUTER SCIENCE TECHNICAL AND NATURAL SCIENCE ELECTIVES"),
                text("Technical electives", 10),
                table([["MATH 322 Mathematical Statistics"]], 20),
            ],
        )
    ]
    groups = parse_electives(pages, 2026, ["COMPUTER SCIENCE (CS)", "MATHEMATICS"])
    assert ("COMPUTER SCIENCE (CS)", "technical") in groups


def test_groups_from_requirements_skips_required_courses():
    rows = [
        row("Two KAZ courses", 12, section="core"),
        row("MATH 162 Calculus II", 8, codes=["MATH 162"]),
    ]
    assert groups_from_requirements(rows, 2026) == {}


def test_groups_from_requirements_reads_open_ended_rows():
    rows = [
        row("Any Math 300– or 400-level courses", 42),
        row("Any two courses from MATH 407, MATH 411", 6, codes=["MATH 407", "MATH 411"], count=2),
    ]
    group = groups_from_requirements(rows, 2026)[("MATHEMATICS", "major")]
    assert group.rules[0].subjects == ("MATH",)
    assert group.rules[0].min_level == 300
    assert group.listed_codes == {"MATH 407", "MATH 411"}
    assert group.count == 2


def test_resolve_keeps_listed_courses_and_expands_rules_by_catalog():
    group = ElectiveGroup(
        admission_year=2026,
        program="COMPUTER SCIENCE (CS)",
        kind="technical",
        courses=[CourseRef(code="MATH 322", title="")],
        rules=[ElectiveRule(subjects=("CSCI",), min_level=200, exclude_required=True)],
    )
    catalog = {"CSCI 151": "Programming", "CSCI 434": "Information Security", "PHYS 161": "Physics"}
    assert group.resolve(catalog, required=frozenset({"CSCI 151"})) == {"MATH 322", "CSCI 434"}


def test_resolve_without_catalog_keeps_only_what_handbook_named():
    group = ElectiveGroup(
        admission_year=2026,
        program="COMPUTER SCIENCE (CS)",
        kind="technical",
        courses=[CourseRef(code="MATH 322", title="")],
        rules=[ElectiveRule(subjects=("CSCI",), min_level=200)],
    )
    assert group.resolve() == {"MATH 322"}


def test_resolve_skips_advisor_rules_by_default():
    group = ElectiveGroup(
        admission_year=2026,
        program="ROBOTICS ENGINEERING",
        kind="technical",
        rules=[ElectiveRule(subjects=("MATH",), advisor_consent=True)],
    )
    catalog = {"MATH 322": "Mathematical Statistics"}
    assert group.resolve(catalog) == set()
    assert group.resolve(catalog, include_advisor=True) == {"MATH 322"}


def test_match_titles_requires_exact_match():
    catalog = {"ROBT 407": "Statistical Methods and Machine Learning", "CSCI 341": "Database Systems"}
    assert match_titles(["Database Systems"], catalog) == {"CSCI 341"}
    # Похожее название — другой курс, и угадывать нельзя
    assert match_titles(["Machine Learning with Applications"], catalog) == set()
