from course_recommender.audit import Audit, SlotStatus
from course_recommender.data.assemble import PlanSlot, Program
from course_recommender.data.transcripts import parse_text
from course_recommender.domain import CompletedCourse, Course, CourseKind
from course_recommender.web import view

TRANSCRIPT = parse_text(
    "Student Name: Кто-то\nPrimary major: Computer Science\nAdmission semester: Fall 2023\n"
)


def course(code, semester=1, credits=6, grade="C-"):
    return Course(
        code=code, title=f"{code} course", credits=credits, kind=CourseKind.MAJOR,
        min_grade=grade, recommended_semester=semester,
    )


def slot(name, semester=8, codes=(), kind="technical"):
    return PlanSlot(
        name=name, semester=semester, term="spring", credits=6,
        kind=kind, eligible_codes=frozenset(codes),
    )


def result(**kwargs):
    program = kwargs.pop("program", None) or Program(
        admission_year=2023, name="COMPUTER SCIENCE (CS)", degree="BSc"
    )
    return Audit(program=program, student=TRANSCRIPT.student(), degree_credits=240, **kwargs)


def test_program_map_groups_by_semester_and_marks_states():
    program = Program(
        admission_year=2023, name="CS", degree="BSc",
        courses={c.code: c for c in (course("CSCI 151", 1), course("CSCI 408", 7))},
        slots=[slot("Technical Elective", 8, ["CSCI 434"])],
    )
    audit = result(
        program=program,
        done=[course("CSCI 151", 1)],
        missing=[course("CSCI 408", 7)],
        slots=[SlotStatus(slot=slot("Technical Elective", 8, ["CSCI 434"]))],
    )
    columns = {c["name"]: c for c in view.program_map(audit, TRANSCRIPT)}

    assert columns["Семестр 1"]["term"] == "Fall 2023"
    assert columns["Семестр 1"]["cells"][0]["state"] == "closed"
    assert columns["Семестр 7"]["cells"][0]["state"] == "missing"
    assert columns["Семестр 8"]["cells"][0]["state"] == "open"
    # Пустые семестры в карту не попадают
    assert "Семестр 2" not in columns


def test_map_key_is_not_called_items():
    # `column.items` в шаблоне разрешилось бы в метод словаря
    columns = view.program_map(result(), TRANSCRIPT)
    assert all("items" not in column for column in columns)


def test_slot_states_cover_every_case():
    closed = SlotStatus(slot=slot("Natural Science"), closed_by="BIOL 101")
    open_slot = SlotStatus(slot=slot("Technical Elective", codes=["CSCI 434"]))
    anything = SlotStatus(slot=slot("Open Elective", kind="general"))
    unknown = SlotStatus(slot=slot("Kazakh Language", kind=None))

    audit = result(slots=[closed, open_slot, anything, unknown])
    page = view.audit_page(audit, TRANSCRIPT)
    states = {item["name"]: item["state"] for item in page["slots"]}

    # Закрытая позиция в список оставшихся не попадает
    assert "Natural Science" not in states
    assert states["Technical Elective"] == "open"
    assert states["Open Elective"] == "any"
    assert states["Kazakh Language"] == "unverified"


def test_credits_split_earned_and_in_progress():
    audit = result(in_progress=[CompletedCourse("CSCI 299", None, 7, credits=6)])
    audit.student.completed.append(CompletedCourse("CSCI 151", 3.0, 1, credits=8))

    credits = view.audit_page(audit, TRANSCRIPT)["credits"]
    assert credits["earned"] == 8
    assert credits["in_progress"] == 6
    assert credits["remaining"] == 232
    # Незачтённое показано отдельной долей, а не смешано с набранным
    assert credits["earned_share"] != credits["progress_share"]


def test_attention_lists_every_kind_of_problem():
    audit = result(
        missing=[course("CSCI 408", 7)],
        low_grade=[(course("CSCI 245", 4, grade="C-"), 1.0)],
        in_progress=[CompletedCourse("CSCI 299", None, 7, credits=6)],
    )
    attention = {item["code"]: item for item in view.audit_page(audit, TRANSCRIPT)["attention"]}

    assert attention["CSCI 245"]["state"] == "retake"
    assert "ниже проходной C-" in attention["CSCI 245"]["detail"]
    assert attention["CSCI 408"]["state"] == "missing"
    assert attention["CSCI 299"]["state"] == "current"


def test_tiles_count_what_needs_doing():
    audit = result(
        missing=[course("CSCI 408", 7)],
        slots=[
            SlotStatus(slot=slot("Technical Elective", codes=["CSCI 434"])),
            SlotStatus(slot=slot("Kazakh Language", kind=None)),
        ],
    )
    tiles = {tile["label"]: tile["n"] for tile in view.audit_page(audit, TRANSCRIPT)["tiles"]}

    assert tiles["обязательных не пройдено"] == 1
    assert tiles["открытые позиции"] == 1
    # Непроверенная позиция считается отдельно: это не «не выполнено»
    assert tiles["не проверено"] == 1


def test_legend_covers_all_states_used_on_the_page():
    page = view.audit_page(result(), TRANSCRIPT)
    assert {item["state"] for item in page["legend"]} == set(view.STATES)
