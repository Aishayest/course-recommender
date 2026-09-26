from course_recommender.data.grades import CourseGrades, SectionGrades
from course_recommender.domain import Course, CourseKind
from course_recommender.recommend import Evidence, Recommendation
from course_recommender.web import view

WEIGHTS = {"need": 0.6, "access": 0.4, "fit": 0.2, "ease": 0.0}


def course(code="CSCI 437", credits=6):
    return Course(code=code, title=f"{code} course", credits=credits, kind=CourseKind.ELECTIVE)


def grades(code="CSCI 437", sections=((1, 2.88, 45, {"A": 20.0, "B": 50.0, "C": 10.0, "W": 12.0}),)):
    return CourseGrades(
        code=code,
        title=code,
        sections=[
            SectionGrades(
                term="Fall 2025", school="SCAI", department="CS", code=code, title=code,
                section=number, graded=graded, average=average, deviation=0.5,
                median=average, shares=shares, letters=graded, instructors=("Лектор",),
            )
            for number, average, graded, shares in sections
        ],
    )


def evidence(**kwargs):
    return Evidence(course=kwargs.pop("course", course()), **kwargs)


def card(evidence_obj, score=0.9, fallback=None, weights=None):
    result = Recommendation(
        course=evidence_obj.course, score=score, evidence=evidence_obj, fallback=fallback
    )
    return view.course_card(1, result, weights or WEIGHTS)


def test_components_show_weight_and_value():
    parts = {part["key"]: part for part in card(evidence(on_plan=True, fill_chance=0.3))["components"]}

    assert parts["need"]["value"] == "1.00"
    assert parts["need"]["weight"] == 0.6
    assert parts["need"]["counted"]
    assert parts["access"]["known"]


def test_component_with_zero_weight_is_counted_out_not_hidden():
    # Слагаемое посчитано, но в балл не вошло — это решение, а не пробел
    parts = {part["key"]: part for part in card(evidence(grades=grades()))["components"]}
    assert parts["ease"]["known"]
    assert not parts["ease"]["counted"]


def test_component_without_data_is_marked_unknown():
    parts = {part["key"]: part for part in card(evidence())["components"]}
    assert not parts["fit"]["known"]
    assert not parts["ease"]["known"]
    # Незнание не подменяется нулём: значение всё равно нейтральное
    assert parts["fit"]["value"] == "0.50"


def test_warnings_name_every_obstacle():
    found = card(
        evidence(needs_permission=True, missing=("MATH 301",), conflicts=("CSCI 435",))
    )["warnings"]
    texts = " ".join(warning["text"] for warning in found)

    assert "согласие преподавателя" in texts
    assert "MATH 301" in texts
    assert "CSCI 435" in texts


def test_access_reports_source_of_every_number():
    access = card(
        evidence(priority_tier=2, mean_fill=0.78, terms_observed=3, fill_chance=0.36)
    )["access"]

    assert access["tier"] == "тир 2"
    assert access["fill"] == 78
    assert "3 семестра" in access["fill_source"]
    assert access["fill_chance_known"]
    assert access["fill_chance"] == 36


def test_access_without_history_says_so():
    access = card(evidence())["access"]
    assert not access["fill_known"]
    assert "истории заполняемости нет" in access["fill_source"]
    assert not access["fill_chance_known"]


def test_grades_spread_across_letters():
    shown = card(evidence(grades=grades()))["grades"]

    assert shown["known"]
    assert shown["average"] == "2.88"
    assert (shown["a"], shown["b"], shown["c"]) == (20, 50, 10)
    assert shown["bad"] == 12
    assert "n=45" in shown["source"]


def test_grades_spread_shown_only_when_it_matters():
    close = grades(sections=((1, 2.9, 40, {}), (2, 3.0, 40, {})))
    wide = grades(sections=((1, 2.0, 40, {}), (2, 3.0, 40, {})))

    assert card(evidence(grades=close))["grades"]["spread"] is None
    assert card(evidence(grades=wide))["grades"]["spread"] == "1.00"


def test_grades_absent_are_not_filled_with_zero():
    shown = card(evidence())["grades"]
    assert not shown["known"]
    assert "нет" in shown["source"]


def test_teacher_record_is_looked_up_by_name():
    shown = card(evidence(grades=grades(), instructors=("Лектор",)))["teacher"]
    person = shown["people"][0]

    assert person["name"] == "Лектор"
    assert person["known"]
    assert person["average"] == "2.88"
    assert person["n"] == 45


def test_teacher_who_never_taught_it_is_marked():
    shown = card(evidence(grades=grades(), instructors=("Новый",)))["teacher"]
    assert not shown["people"][0]["known"]


def test_teacher_unknown_when_schedule_is_silent():
    shown = card(evidence())["teacher"]
    assert not shown["known"]
    assert "не указано" in shown["note"]


def test_card_carries_fallback_and_similarity():
    shown = card(evidence(fit_closest="CSCI 390"), fallback=course("CSCI 435"))
    assert shown["fit_closest"] == "CSCI 390"
    assert shown["fallback"] == "CSCI 435"


def test_page_keeps_the_weights_it_was_given():
    page = view.courses_page([], {"need": 0.3, "access": 0.7, "fit": 0.0}, "Fall 2026", [])

    assert page["count"] == 0
    assert page["term"] == "Fall 2026"
    controls = {control["key"]: control["value"] for control in page["controls"]}
    assert controls["need"] == 0.3
    assert controls["access"] == 0.7
    assert controls["ease"] == 0.0


def test_no_courses_key_shadows_a_dict_method():
    from course_recommender.recommend import Recommendation

    shown = evidence(grades=grades(), instructors=("Лектор",), priority_tier=1, mean_fill=0.8)
    page = view.courses_page(
        [Recommendation(course=shown.course, score=0.9, evidence=shown)],
        WEIGHTS, "Fall 2026", [],
    )
    assert view.shadows_dict_methods(page) == set()
