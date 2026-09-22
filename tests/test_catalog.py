from course_recommender.conditions import All, CourseNeeded, from_json, to_json
from course_recommender.data.catalog import (
    Catalog,
    build,
    season,
    term_key,
)
from course_recommender.data.catalog import (
    from_json as catalog_from_json,
)
from course_recommender.data.catalog import (
    to_json as catalog_to_json,
)
from course_recommender.data.registration import Audience, CourseOffering


def offering(code, **kwargs):
    return CourseOffering(
        term=kwargs.pop("term", "Fall 2026"),
        school=kwargs.pop("school", "SCAI"),
        department=kwargs.pop("department", "Computer Science"),
        code=code,
        title=kwargs.pop("title", ""),
        credits_ects=kwargs.pop("credits_ects", 6),
        **kwargs,
    )


def test_term_key_orders_terms_inside_a_year():
    assert term_key("Spring 2025") < term_key("Summer 2025") < term_key("Fall 2025")
    assert term_key("Fall 2024") < term_key("Spring 2025")


def test_season():
    assert season("Spring 2026") == "Spring"
    assert season("что-то ещё") is None


def test_build_collects_terms_of_one_course():
    catalog = build(
        [
            offering("CSCI 152", term="Spring 2025"),
            offering("CSCI 152", term="Spring 2026"),
            offering("CSCI 152", term="Summer 2025"),
        ]
    )
    assert catalog.get("CSCI 152").terms == ("Spring 2025", "Summer 2025", "Spring 2026")


def test_newest_term_wins_for_title_and_department():
    catalog = build(
        [
            offering("CSCI 152", term="Fall 2026", title="Performance and Data Structures"),
            offering("CSCI 152", term="Fall 2023", title="Data Structures"),
        ]
    )
    assert catalog.get("CSCI 152").title == "Performance and Data Structures"


def test_semesters_offered_from_seasons():
    spring = build([offering("ACCT 201", term="Spring 2025")]).get("ACCT 201")
    both = build(
        [offering("CSCI 151", term="Fall 2025"), offering("CSCI 151", term="Spring 2026")]
    ).get("CSCI 151")
    summer = build([offering("ENG 180", term="Summer 2025")]).get("ENG 180")

    assert spring.semesters_offered == (2, 4, 6, 8)
    assert both.semesters_offered == (1, 2, 3, 4, 5, 6, 7, 8)
    # Лето в сквозную нумерацию плана не попадает: пусто значит "неизвестно"
    assert summer.semesters_offered == ()


def test_prerequisite_uses_latest_term_up_to_the_asked_one():
    entry = build(
        [
            offering("CSCI 231", term="Fall 2023", prerequisite=CourseNeeded("CSCI 151")),
            offering("CSCI 231", term="Fall 2026", prerequisite=CourseNeeded("CSCI 152")),
        ]
    ).get("CSCI 231")

    assert entry.prerequisite("Fall 2025") == CourseNeeded("CSCI 151")
    assert entry.prerequisite("Fall 2026") == CourseNeeded("CSCI 152")
    # За семестр раньше всех известных остаётся последнее, что вообще есть
    assert entry.prerequisite("Fall 2020") == CourseNeeded("CSCI 152")
    assert entry.prerequisite() == CourseNeeded("CSCI 152")


def test_offered_falls_back_to_season_when_term_is_unknown():
    catalog = build(
        [
            offering("CSCI 152", term="Spring 2025"),
            offering("CSCI 151", term="Fall 2025"),
        ]
    )
    assert catalog.offered("Spring 2025") == {"CSCI 152"}
    # Документа за Spring 2026 нет — остаётся сезон
    assert catalog.offered("Spring 2026") == {"CSCI 152"}
    assert catalog.offered() == {"CSCI 151", "CSCI 152"}


def test_priority_for_reads_tiers_of_the_asked_term():
    entry = build(
        [
            offering("CSCI 333", term="Spring 2025", priorities=[[Audience(year=3, raw="3 year")]]),
            offering("CSCI 333", term="Fall 2026", priorities=[[Audience(year=4, raw="4 year")]]),
        ]
    ).get("CSCI 333")

    assert entry.priority_for(3, None, None, "Spring 2025") == 1
    assert entry.priority_for(3, None, None, "Fall 2026") is None
    assert entry.priority_for(4, None, None, "Fall 2026") == 1


def test_catalog_survives_saving_and_reading_back():
    catalog = build(
        [
            offering(
                "CSCI 231",
                term="Fall 2026",
                title="Computer Systems",
                prerequisite=All((CourseNeeded("CSCI 151", min_grade="C-"),)),
                priorities=[[Audience(year=2, school="SCAI", raw="2 year SCAI")]],
            )
        ]
    )
    restored = catalog_from_json(catalog_to_json(catalog))
    entry = restored.get("CSCI 231")

    assert entry.title == "Computer Systems"
    assert entry.terms == ("Fall 2026",)
    assert entry.prerequisite() == All((CourseNeeded("CSCI 151", min_grade="C-"),))
    assert entry.priority_for(2, "SCAI", None, "Fall 2026") == 1


def test_course_of_entry_carries_terms_and_condition():
    entry = build(
        [offering("CSCI 434", term="Fall 2026", title="Information Security")]
    ).get("CSCI 434")
    course = entry.course()

    assert course.title == "Information Security"
    assert course.credits == 6
    assert course.semesters_offered == (1, 3, 5, 7)


def test_empty_catalog_has_no_terms():
    assert Catalog().terms == ()
    assert len(Catalog()) == 0


def test_condition_tree_survives_json():
    node = All((CourseNeeded("CSCI 151", title="Programming", min_grade="C-"),))
    assert from_json(to_json(node)) == node
    assert from_json(to_json(None)) is None
