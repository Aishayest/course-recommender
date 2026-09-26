from datetime import time

from course_recommender.data.schedule import Meeting, Section
from course_recommender.domain import Course, CourseKind
from course_recommender.plan import Choice, Semester, assemble, rank_sections
from course_recommender.recommend import Evidence
from course_recommender.web import view


def course(code="CSCI 437", credits=6):
    return Course(code=code, title=f"{code} course", credits=credits, kind=CourseKind.ELECTIVE)


def section(code="CSCI 437", label="1L", days=("M", "W"), start=time(10, 30), end=time(11, 45), faculty=("Лектор",)):
    return Section(
        term="Fall 2026", code=code, section=label, faculty=tuple(faculty),
        meetings=[Meeting(days=days, start=start, end=end)],
    )


def online(code="CSCI 408"):
    return Section(term="Fall 2026", code=code, section="1L", meetings=[Meeting(online=True)])


def choice(section_obj=None, code="CSCI 437", slot="Technical Elective", alternatives=(), practice=0):
    return Choice(
        evidence=Evidence(course=course(code), fills_slot=slot),
        section=section_obj if section_obj is not None else section(code),
        alternatives=tuple(alternatives),
        practice=practice,
    )


def semester(choices=(), target=30, left_out=()):
    return Semester(
        term="Fall 2026", target_credits=target, choices=list(choices), left_out=list(left_out)
    )


def test_block_is_placed_by_the_clock():
    grid = view.week_grid(semester([choice()]))
    monday = next(day for day in grid["days"] if day["name"] == "Пн")
    block = monday["blocks"][0]

    # 10:30 при сетке с девяти и часе в 56 пикселей
    assert block["top"] == round(1.5 * 56)
    assert block["height"] == round(75 / 60 * 56)
    assert block["time"] == "10:30–11:45"
    assert block["chosen"]


def test_one_meeting_lands_in_every_day_it_runs():
    grid = view.week_grid(semester([choice()]))
    days = {day["name"]: len(day["blocks"]) for day in grid["days"]}
    assert days["Пн"] == 1 and days["Ср"] == 1
    assert days["Вт"] == 0


def test_alternative_section_is_drawn_apart():
    other = section(label="2L", days=("T",), start=time(15, 0), end=time(16, 15))
    grid = view.week_grid(semester([choice(alternatives=[other])]))
    tuesday = next(day for day in grid["days"] if day["name"] == "Вт")

    assert not tuesday["blocks"][0]["chosen"]
    assert tuesday["blocks"][0]["note"] == "другая секция"


def test_online_course_goes_above_the_grid():
    grid = view.week_grid(semester([choice(online(), code="CSCI 408")]))
    assert grid["offline"] == ["CSCI 408"]
    assert all(not day["blocks"] for day in grid["days"])


def test_plan_page_counts_credits_and_gaps():
    page = view.plan_page(semester([choice(), choice(code="MATH 417")]), "Fall 2026")

    assert page["credits"] == 12
    assert page["target"] == 30
    assert page["missing"] == 18
    assert page["count"] == 2
    assert page["registration"] == ["CSCI 437 1L", "MATH 417 1L"]


def test_plan_page_marks_a_course_without_a_schedule():
    page = view.plan_page(semester([Choice(evidence=Evidence(course=course()))]), "Fall 2026")
    assert page["courses"][0]["unscheduled"]


def test_plan_page_warns_when_practice_is_scarce():
    page = view.plan_page(semester([choice(practice=1)]), "Fall 2026")
    assert page["courses"][0]["practice"] == 1


def test_left_out_reasons_are_carried_over():
    left = [(Evidence(course=course("CSCI 423")), "пересекается по времени с CSCI 435")]
    page = view.plan_page(semester([], left_out=left), "Fall 2026")
    assert page["left_out"][0]["code"] == "CSCI 423"
    assert "пересекается" in page["left_out"][0]["reason"]


def test_chosen_section_is_tried_first():
    first, second = section(label="1L"), section(label="2L", start=time(15, 0), end=time(16, 15))
    ranked = rank_sections([first, second], None, preferred="2L")
    assert [s.section for s in ranked] == ["2L", "1L"]


def test_assemble_takes_the_section_the_student_asked_for():
    options = [section(label="1L"), section(label="2L", start=time(15, 0), end=time(16, 15))]
    pool = [Evidence(course=course(), fills_slot="Technical Elective")]
    capacity = {"Technical Elective": 1}

    default = assemble(pool, {"CSCI 437": options}, 6, "Fall 2026", capacity)
    picked = assemble(pool, {"CSCI 437": options}, 6, "Fall 2026", capacity, prefer={"CSCI 437": "2L"})

    assert default.choices[0].label == "1L"
    assert picked.choices[0].label == "2L"


def test_no_view_key_shadows_a_dict_method():
    # `page.items` в шаблоне вернёт метод словаря, а не значение
    page = view.plan_page(semester([choice(alternatives=[section(label="2L")])]), "Fall 2026")
    assert view.shadows_dict_methods(page) == set()


def test_shadow_check_actually_catches_the_trap():
    assert view.shadows_dict_methods({"items": [1]}) == {"items"}
    assert view.shadows_dict_methods({"a": {"keys": 1}}) == {"keys"}
    assert view.shadows_dict_methods({"a": [{"values": 1}]}) == {"values"}
