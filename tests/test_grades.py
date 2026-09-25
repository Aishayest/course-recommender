from datetime import UTC, datetime

from course_recommender.data.grades import (
    CourseGrades,
    SectionGrades,
    attach_instructors,
    by_course,
    instructors_from,
    parse_row,
    parse_text,
)
from course_recommender.data.schedule import Section, Snapshot

REPORT = """E. Detailed Grade Distribution by Undergraduate Course and Department
E5.Computer Science
Course Course Title Sectio # GPA Ave SD Media %A %B %C %D %F %P %I %AU %W # Letter
n # Grades GPA n GPA Grades
CSCI 231 Computer Systems and 1 89 2.39 1.18 2.67 19.4 28.6 20.4 13.3 9.2 0.0 0.0 0.0 9.2 98
Organization
CSCI 231 Computer Systems and 2 83 2.19 1.03 2.33 6.2 33.3 29.2 9.4 8.3 0.0 0.0 0.0 13.5 96
Organization
CSCI 399 Internship II 1 0 1
Overall 172 2.29 1.10 2.50 12.8 31.0 24.8 11.4 8.8 0.0 0.0 0.0 11.4 194
"""


def section(code, number, term="Fall 2025", faculty=("Кто-то",), kind="L"):
    return Section(term=term, code=code, section=f"{number}{kind}", faculty=tuple(faculty))


def grades(code="CSCI 231", number=1, average=2.4, graded=50, term="Fall 2025", shares=None):
    return SectionGrades(
        term=term, school="SEDS", department="Computer Science", code=code,
        title=code, section=number, graded=graded, average=average,
        deviation=1.0, median=average, shares=shares or {}, letters=graded,
    )


def test_parse_row_reads_all_columns():
    line = "CSCI 231 Computer Systems and 1 89 2.39 1.18 2.67 19.4 28.6 20.4 13.3 9.2 0.0 0.0 0.0 9.2 98"
    row = parse_row(line, "Fall 2025", "SEDS", "Computer Science")
    assert row.code == "CSCI 231"
    assert row.section == 1
    assert row.graded == 89
    assert row.average == 2.39
    assert row.median == 2.67
    assert row.shares["A"] == 19.4
    assert row.shares["W"] == 9.2
    assert row.letters == 98


def test_row_without_grades_is_skipped():
    # У курса нет ни среднего, ни медианы — в статистике ему делать нечего
    assert parse_row("CSCI 399 Internship II 1 0 1", "Fall 2025", "SEDS", "CS") is None


def test_parse_text_picks_up_department_and_skips_totals():
    rows = parse_text(REPORT, term="Fall 2025", school="SEDS")
    assert [r.section for r in rows] == [1, 2]
    assert {r.department for r in rows} == {"Computer Science"}
    assert all(r.code == "CSCI 231" for r in rows)


def test_risky_share_counts_bad_endings():
    row = grades(shares={"D": 13.3, "F": 9.2, "W": 9.2})
    assert row.withdrew == 9.2
    assert row.failed == 9.2
    assert round(row.risky, 1) == 31.7


def test_course_average_is_weighted_by_number_of_grades():
    course = by_course([grades(average=2.0, graded=10), grades(number=2, average=4.0, graded=30)])
    assert course["CSCI 231"].average == 3.5
    assert course["CSCI 231"].graded == 40


def test_spread_compares_sections_inside_one_term():
    course = CourseGrades(
        code="CSCI 231",
        sections=[
            grades(average=2.0, term="Fall 2025"),
            grades(number=2, average=2.6, term="Fall 2025"),
            grades(number=1, average=1.0, term="Spring 2026"),
        ],
    )
    # Разброс внутри семестра, а не между семестрами: иначе он бы мерил
    # не преподавателей, а разные наборы студентов
    assert round(course.spread("Fall 2025"), 2) == 0.6
    assert course.spread("Spring 2026") is None  # одна секция — сравнивать не с чем


def test_course_without_grades_has_no_average():
    assert CourseGrades(code="CSCI 231").average is None
    assert CourseGrades(code="CSCI 231").spread() is None


def test_instructors_come_from_lectures_not_from_labs():
    snapshot = Snapshot(
        term="Fall 2025",
        taken_at=datetime(2025, 12, 1, tzinfo=UTC),
        sections=[
            section("CSCI 231", 1, faculty=("Лектор",), kind="L"),
            section("CSCI 231", 1, faculty=("Ассистент",), kind="Lb"),
        ],
    )
    assert instructors_from([snapshot])[("Fall 2025", "CSCI 231", 1)] == ("Лектор",)


def test_instructors_fall_back_when_there_is_no_lecture():
    snapshot = Snapshot(
        term="Fall 2025",
        taken_at=None,
        sections=[section("CSCI 299", 1, faculty=("Руководитель",), kind="I")],
    )
    assert instructors_from([snapshot])[("Fall 2025", "CSCI 299", 1)] == ("Руководитель",)


def test_attach_instructors_joins_on_course_and_section_number():
    snapshot = Snapshot(
        term="Fall 2025",
        taken_at=None,
        sections=[
            section("CSCI 231", 1, faculty=("Первый",)),
            section("CSCI 231", 2, faculty=("Второй",)),
        ],
    )
    rows = attach_instructors([grades(number=1), grades(number=2)], [snapshot])
    assert [r.instructors for r in rows] == [("Первый",), ("Второй",)]


def test_attach_instructors_leaves_unknown_sections_alone():
    rows = attach_instructors([grades(number=9)], [Snapshot(term="Fall 2025", taken_at=None)])
    assert rows[0].instructors == ()


def test_by_instructor_groups_sections():
    rows = attach_instructors(
        [grades(number=1), grades(number=2)],
        [
            Snapshot(
                term="Fall 2025",
                taken_at=None,
                sections=[
                    section("CSCI 231", 1, faculty=("Один",)),
                    section("CSCI 231", 2, faculty=("Один",)),
                ],
            )
        ],
    )
    course = by_course(rows)["CSCI 231"]
    assert list(course.by_instructor()) == ["Один"]
    assert len(course.by_instructor()["Один"]) == 2
