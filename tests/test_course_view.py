from course_recommender.data.grades import CourseGrades, SectionGrades
from course_recommender.web import view


def section(number=1, average=2.4, graded=50, term="Fall 2025", teacher="Лектор", withdrew=5.0):
    return SectionGrades(
        term=term, school="SCAI", department="Computer Science", code="CSCI 231",
        title="Computer Systems", section=number, graded=graded, average=average,
        deviation=1.0, median=average, shares={"W": withdrew, "D": 3.0, "F": 2.0},
        letters=graded, instructors=(teacher,),
    )


def grades(*sections):
    return CourseGrades(code="CSCI 231", title="Computer Systems", sections=list(sections))


def test_course_without_reports_says_so():
    page = view.course_page("CSCI 231", None)
    assert not page["known"]
    assert "нет" in page["note"]
    # Ноль вместо неизвестного не подставлен
    assert "average" not in page


def test_sections_are_listed_with_teacher_and_numbers():
    page = view.course_page("CSCI 231", grades(section(1, 2.39, 89, teacher="Первый")))
    row = page["rows"][0]

    assert page["average"] == "2.39"
    assert row["teacher"] == "Первый"
    assert row["n"] == 89
    assert row["withdrew"] == "5.0%"
    # Шкала 0–4: 2.39 это примерно 60%
    assert row["percent"] == 60
    assert page["marker"] == 60


def test_small_section_is_marked_as_thin():
    page = view.course_page("CSCI 231", grades(section(1, graded=10), section(2, graded=40)))
    assert page["rows"][0]["thin"]
    assert not page["rows"][1]["thin"]


def test_spread_is_compared_with_the_university_median():
    wide = view.course_page("CSCI 231", grades(section(1, 2.0), section(2, 2.9)))
    narrow = view.course_page("CSCI 231", grades(section(1, 2.5), section(2, 2.6)))

    assert wide["spread"] == "0.90"
    assert wide["spread_matters"]
    assert narrow["spread"] == "0.10"
    assert not narrow["spread_matters"]


def test_single_section_has_nothing_to_compare():
    assert view.course_page("CSCI 231", grades(section(1))) ["spread"] is None


def test_terms_are_aggregated_separately():
    page = view.course_page(
        "CSCI 231",
        grades(
            section(1, 2.0, 100, term="Fall 2025"),
            section(2, 3.0, 100, term="Fall 2025"),
            section(1, 2.5, 50, term="Spring 2026"),
        ),
    )
    by_term = {item["term"]: item for item in page["by_term"]}

    assert by_term["Fall 2025"]["average"] == "2.50"
    assert by_term["Fall 2025"]["n"] == 200
    assert by_term["Fall 2025"]["sections"] == 2
    assert by_term["Spring 2026"]["average"] == "2.50"


def test_teachers_are_sorted_by_result():
    page = view.course_page(
        "CSCI 231",
        grades(section(1, 2.0, 50, teacher="Слабее"), section(2, 3.0, 50, teacher="Сильнее")),
    )
    assert [teacher["name"] for teacher in page["teachers"]] == ["Сильнее", "Слабее"]
    assert page["teachers"][0]["average"] == "3.00"


def test_title_falls_back_through_the_sources():
    assert view.course_page("CSCI 231", None)["title"] == "CSCI 231"


def test_no_course_key_shadows_a_dict_method():
    page = view.course_page("CSCI 231", grades(section(1), section(2, 3.0)))
    assert view.shadows_dict_methods(page) == set()
