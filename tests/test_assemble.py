from course_recommender.data.assemble import (
    attach_catalog,
    attach_electives,
    build_courses,
    build_program,
    build_slots,
    core_kinds,
    dominant_subject,
    electives_of,
    resolve_kind,
    semester_index,
)
from course_recommender.data.catalog import build as build_catalog
from course_recommender.data.electives import ElectiveGroup, ElectiveRule
from course_recommender.data.handbook import CourseRef, PlanEntry
from course_recommender.data.registration import CourseOffering
from course_recommender.data.requirements import RequirementRow
from course_recommender.domain import CourseKind


def entry(code, *, year=1, term="fall", credits=(6,), grade="C-", title="Title", program="CS"):
    options = [CourseRef(code=code, title=title)] if code else [CourseRef(None, title)]
    return PlanEntry(
        admission_year=2026,
        program=program,
        degree="BSc",
        study_year=year,
        term=term,
        options=options,
        min_grade=grade,
        credits=credits,
    )


def row(name, credits, *, section="major", explanation="", codes=(), total=False, grade=None):
    return RequirementRow(
        admission_year=2026,
        program="CS",
        section=section,
        name=name,
        credits=credits,
        explanation=explanation,
        courses=[CourseRef(code=c, title="") for c in codes],
        is_total=total,
        min_grade=grade,
    )


def test_semester_index_counts_through_all_four_years():
    assert semester_index(1, "fall") == 1
    assert semester_index(1, "spring") == 2
    assert semester_index(2, "spring") == 4
    assert semester_index(4, "spring") == 8


def test_dominant_subject_uses_senior_years():
    entries = [
        entry("HST 100", year=1),
        entry("CSCI 341", year=3),
        entry("CSCI 361", year=3),
        entry("MATH 273", year=3),
    ]
    assert dominant_subject(entries) == "CSCI"


def test_dominant_subject_none_without_senior_courses():
    assert dominant_subject([entry("HST 100", year=1)]) is None


def test_own_requirements_beat_profile_prefix():
    own = {"CSCI 151": CourseKind.CORE}
    assert resolve_kind("CSCI 151", own, {}, "CSCI") is CourseKind.CORE


def test_profile_prefix_beats_shared_map():
    # у SSH-специальностей CSCI идёт как общеуниверситетский,
    # но для программы CS это профильный курс
    shared = {"CSCI 151": CourseKind.CORE}
    assert resolve_kind("CSCI 151", {}, shared, "CSCI") is CourseKind.MAJOR


def test_shared_map_used_when_nothing_else_knows():
    shared = {"HST 100": CourseKind.CORE}
    assert resolve_kind("HST 100", {}, shared, "CSCI") is CourseKind.CORE


def test_unknown_course_stays_unspecified():
    assert resolve_kind("ASC 100", {}, {}, "CSCI") is CourseKind.UNSPECIFIED


def test_build_courses_sets_semester_and_offering():
    courses = build_courses([entry("CSCI 231", year=2, term="fall")], {}, {}, "CSCI")
    course = courses["CSCI 231"]
    assert course.recommended_semester == 3
    assert course.semesters_offered == (1, 3, 5, 7)
    assert course.credits == 6
    assert course.min_grade == "C-"


def test_spring_course_offered_in_even_semesters():
    courses = build_courses([entry("CSCI 152", year=1, term="spring")], {}, {}, "CSCI")
    assert courses["CSCI 152"].semesters_offered == (2, 4, 6, 8)


def test_repeated_course_keeps_earliest_semester():
    entries = [entry("KAZ 101", year=3, term="fall"), entry("KAZ 101", year=1, term="fall")]
    assert build_courses(entries, {}, {}, None)["KAZ 101"].recommended_semester == 1


def test_build_slots_collects_placeholders_only():
    entries = [entry("CSCI 151"), entry(None, title="General Elective")]
    slots = build_slots(entries)
    assert [s.name for s in slots] == ["General Elective"]
    assert slots[0].semester == 1


def test_core_kinds_ignores_electives_and_totals():
    rows = [
        row("History of Kazakhstan", 6, section="core", codes=["HST 100"]),
        row("Electives", 66, section="core", codes=["BIOL 321"]),
        row("Total Degree Credits", 240, section="core", codes=["HST 999"], total=True),
    ]
    assert core_kinds(rows) == {"HST 100": CourseKind.CORE}


def test_build_program_collects_totals_and_grade():
    entries = [entry("CSCI 151"), entry("CSCI 341", year=3)]
    rows = [
        row("Elementary Courses", 12, codes=["CSCI 151"]),
        row("Total Major Credits", 72, total=True, grade="C-"),
        row("Total Degree Credits", 240, total=True),
    ]
    program = build_program(entries, rows, 2026, "CS")
    assert program.total_credits == 240
    assert program.min_major_grade == "C-"
    assert program.degree == "BSc"
    # итоговые строки не становятся требованиями
    assert [r.required_credits for r in program.requirements] == [12]


def test_semester_courses_filters_by_plan_position():
    entries = [entry("CSCI 151", year=1), entry("CSCI 231", year=2, term="fall")]
    program = build_program(entries, [], 2026, "CS")
    assert [c.code for c in program.semester_courses(3)] == ["CSCI 231"]


def offering(code, prerequisite=None, *, term="Fall 2026", title="", credits=6, school="SCAI"):
    return CourseOffering(
        term=term,
        school=school,
        department="Computer Science",
        code=code,
        title=title,
        credits_ects=credits,
        prerequisite=prerequisite,
    )


def test_attach_catalog_sets_condition():
    from course_recommender.conditions import All, CourseNeeded

    programs = {"CS": build_program([entry("CSCI 151"), entry("CSCI 231", year=2)], [], 2026, "CS")}
    catalog = build_catalog(
        [offering("CSCI 231", CourseNeeded("CSCI 151", min_grade="C-")), offering("CSCI 151")]
    )
    updated = attach_catalog(programs, catalog)

    courses = programs["CS"].courses
    assert updated == 2
    assert courses["CSCI 231"].requirement == CourseNeeded("CSCI 151", min_grade="C-")
    # курс без пререквизитов получает пустое условие, а не None
    assert courses["CSCI 151"].requirement == All(())


def test_attach_catalog_leaves_unknown_courses_alone():
    programs = {"CS": build_program([entry("CSCI 152")], [], 2026, "CS")}
    assert attach_catalog(programs, build_catalog([offering("OTHER 101")])) == 0
    assert programs["CS"].courses["CSCI 152"].requirement is None


def test_attach_catalog_takes_real_terms_from_catalog():
    # План ставит курс в осенний семестр, а читают его и весной тоже
    programs = {"CS": build_program([entry("CSCI 152", term="fall")], [], 2026, "CS")}
    catalog = build_catalog(
        [offering("CSCI 152", term="Spring 2026"), offering("CSCI 152", term="Spring 2025")]
    )
    attach_catalog(programs, catalog)
    assert programs["CS"].courses["CSCI 152"].semesters_offered == (2, 4, 6, 8)


def test_attach_catalog_uses_condition_of_the_asked_term():
    from course_recommender.conditions import CourseNeeded

    programs = {"CS": build_program([entry("CSCI 231", year=2)], [], 2026, "CS")}
    catalog = build_catalog(
        [
            offering("CSCI 231", CourseNeeded("CSCI 151"), term="Fall 2024"),
            offering("CSCI 231", CourseNeeded("CSCI 152"), term="Fall 2026"),
        ]
    )
    attach_catalog(programs, catalog, term="Fall 2025")
    # За Fall 2025 условия нет, берётся последнее известное до него
    assert programs["CS"].courses["CSCI 231"].requirement == CourseNeeded("CSCI 151")


def test_build_slots_labels_elective_positions():
    slots = build_slots([entry(None, year=4, title="Technical Elective 2")])
    assert slots[0].kind == "technical"


def test_attach_electives_fills_slots_from_program_own_list():
    program = build_program(
        [entry("CSCI 151", year=1), entry(None, year=4, title="Technical Elective")],
        [],
        2026,
        "COMPUTER SCIENCE (CS)",
        electives={
            "technical": ElectiveGroup(
                admission_year=2026,
                program="COMPUTER SCIENCE (CS)",
                kind="technical",
                courses=[CourseRef(code="MATH 322", title="")],
                rules=[ElectiveRule(subjects=("CSCI",), min_level=200, exclude_required=True)],
            )
        },
    )
    catalog = build_catalog(
        [
            offering("MATH 322", title="Mathematical Statistics"),
            offering("CSCI 434", title="Information Security"),
            offering("CSCI 151", title="Programming"),
        ]
    )
    added = attach_electives({program.name: program}, catalog)

    slot = next(s for s in program.slots if s.kind == "technical")
    assert slot.eligible_codes == {"MATH 322", "CSCI 434"}
    # CSCI 151 обязателен по плану — свободную позицию им не закрыть
    assert "CSCI 151" not in slot.eligible_codes
    assert added == 2
    assert program.courses["CSCI 434"].kind is CourseKind.ELECTIVE
    assert program.courses["CSCI 434"].credits == 6


def test_attach_electives_adds_only_courses_present_in_catalog():
    # handbook перечисляет и то, что в этом семестре не читают
    program = build_program(
        [entry(None, year=4, title="Technical Elective")],
        [],
        2026,
        "COMPUTER SCIENCE (CS)",
        electives={
            "technical": ElectiveGroup(
                admission_year=2026,
                program="COMPUTER SCIENCE (CS)",
                kind="technical",
                courses=[CourseRef(code="PHYS 270", title=""), CourseRef(code="MATH 322", title="")],
            )
        },
    )
    attach_electives(
        {program.name: program},
        build_catalog([offering("MATH 322", title="Mathematical Statistics")]),
    )

    slot = program.slots[0]
    # Позиция закрывается обоими — так сказал handbook
    assert slot.eligible_codes == {"PHYS 270", "MATH 322"}
    # А предложить можно только то, что читают
    assert set(program.courses) == {"MATH 322"}


def test_electives_of_falls_back_to_university_wide_lists():
    own = ElectiveGroup(admission_year=2026, program="SOCIOLOGY", kind="major")
    shared = ElectiveGroup(admission_year=2026, program="", kind="humanities")
    groups = {("SOCIOLOGY", "major"): own, ("", "humanities"): shared}

    resolved = electives_of(groups, "SOCIOLOGY")
    assert resolved["major"] is own
    assert resolved["humanities"] is shared
    assert "major" not in electives_of(groups, "PHYSICS")
