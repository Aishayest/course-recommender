from course_recommender.data.descriptions import (
    CourseDescription,
    Descriptions,
    from_json,
    parse_entry,
    to_json,
)


def entry(code="CSCI 447", **kwargs):
    row = {
        "ABBR": code,
        "TITLE": "   Machine Learning: Theory and Practice",
        "SHORTDESC": "Students will be introduced to  a variety of algorithms.",
        "CRECTS": "6",
        "ACADEMICLEVEL": "Undergraduate",
        "SCHOOLABBR": "SEDS",
        "DEPARTMENT": "Computer Science",
        "PREREQ": "n/a",
    }
    row.update(kwargs)
    return parse_entry(row)


def test_parse_entry_cleans_whitespace_and_placeholders():
    course = entry()
    assert course.code == "CSCI 447"
    assert course.title == "Machine Learning: Theory and Practice"
    assert course.description == "Students will be introduced to a variety of algorithms."
    assert course.credits_ects == 6
    # каталог пишет "n/a" там, где ничего нет
    assert course.prerequisite == ""


def test_entry_without_a_code_is_dropped():
    assert parse_entry({"ABBR": "  ", "TITLE": "Что-то"}) is None


def test_text_joins_title_and_description():
    assert entry().text.startswith("Machine Learning: Theory and Practice. Students")


def test_text_falls_back_to_the_title_alone():
    # У трети курсов описания нет, но название есть всегда
    course = entry(SHORTDESC="n/a")
    assert not course.has_description
    assert course.text == "Machine Learning: Theory and Practice"


def test_cross_listed_code_is_found_by_its_parts():
    catalog = Descriptions(courses={"PLS 204": entry("PLS 204")})
    # В наших документах такой курс записан одним кодом через косую черту
    assert catalog.get("ANT 204/PLS 204").code == "PLS 204"
    assert catalog.get("ANT 204") is None


def test_undergraduate_filter():
    catalog = Descriptions(
        courses={
            "CSCI 447": entry(),
            "CSCI 647": entry("CSCI 647", ACADEMICLEVEL="Graduate"),
        }
    )
    assert list(catalog.undergraduate) == ["CSCI 447"]


def test_texts_skips_courses_without_any_text():
    catalog = Descriptions(
        courses={
            "CSCI 447": entry(),
            "X 100": CourseDescription(code="X 100", title=""),
        }
    )
    assert list(catalog.texts()) == ["CSCI 447"]


def test_texts_can_be_limited_to_given_codes():
    catalog = Descriptions(courses={"CSCI 447": entry(), "PLS 204": entry("PLS 204")})
    assert list(catalog.texts(["PLS 204", "НЕТ 100"])) == ["PLS 204"]


def test_catalog_survives_saving_and_reading_back():
    catalog = Descriptions(courses={"CSCI 447": entry()})
    restored = from_json(to_json(catalog))
    assert restored.get("CSCI 447") == catalog.get("CSCI 447")
    assert len(restored) == 1
