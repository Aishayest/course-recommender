from datetime import date, time

from course_recommender.data.schedule import (
    Meeting,
    Section,
    Snapshot,
    is_continuation,
    merge_sections,
    parse_date,
    parse_days,
    parse_faculty,
    parse_meetings,
    parse_room,
    parse_time_range,
)


def section(code="CSCI 341", label="1L", enrolled=10, capacity=20, meetings=None, level="UG"):
    return Section(
        term="Fall 2026",
        code=code,
        section=label,
        enrolled=enrolled,
        capacity=capacity,
        meetings=list(meetings or []),
        level=level,
    )


def test_parse_days_drops_repeats():
    assert parse_days("M W F") == ("M", "W", "F")
    # однодневные занятия печатают день повторами: "T T T T T T T"
    assert parse_days("T T T T T T T") == ("T",)
    assert parse_days("") == ()


def test_parse_time_range():
    assert parse_time_range("10:30 AM-11:45 AM") == (time(10, 30), time(11, 45))
    assert parse_time_range("01:30 PM-02:45 PM") == (time(13, 30), time(14, 45))
    assert parse_time_range("") == (None, None)


def test_parse_meetings_online():
    meetings = parse_meetings("", "Online/Distant")
    assert meetings == [Meeting(online=True)]


def test_parse_meetings_multiple_ranges_in_one_cell():
    meetings = parse_meetings("T", "10:00 AM-11:15 AM 11:00 AM-12:15 PM")
    assert len(meetings) == 2
    assert meetings[0].start == time(10, 0)
    assert meetings[1].start == time(11, 0)


def test_parse_room_with_capacity():
    assert parse_room("8.310 - cap:30") == ("8.310", 30)
    assert parse_room("online - cap:0") == ("online", 0)
    assert parse_room("") == (None, None)


def test_parse_faculty_handles_tba():
    assert parse_faculty("Aziza Bakytzhanova, Jaehyeon Kim") == ("Aziza Bakytzhanova", "Jaehyeon Kim")
    assert parse_faculty("TBA TBA") == ()


def test_parse_date():
    assert parse_date("17-AUG-26") == date(2026, 8, 17)
    assert parse_date("") is None


def test_section_label_split():
    assert (section(label="10CLb").number, section(label="10CLb").kind) == (10, "CLb")
    assert section(label="1Int").kind == "Int"


def test_seat_arithmetic():
    full = section(enrolled=20, capacity=20)
    over = section(enrolled=34, capacity=27)
    assert full.is_full and not full.is_over_capacity
    assert over.is_full and over.is_over_capacity
    assert over.seats_left == -7
    assert round(over.fill_rate, 2) == 1.26


def test_meetings_overlap_same_day():
    a = Meeting(("T", "R"), time(10, 30), time(11, 45))
    b = Meeting(("R",), time(11, 0), time(12, 0))
    assert a.overlaps(b) and b.overlaps(a)


def test_meetings_touching_but_not_overlapping():
    a = Meeting(("M",), time(9, 0), time(10, 0))
    b = Meeting(("M",), time(10, 0), time(11, 0))
    assert not a.overlaps(b)


def test_meetings_on_different_days_do_not_overlap():
    a = Meeting(("M",), time(9, 0), time(10, 0))
    b = Meeting(("T",), time(9, 0), time(10, 0))
    assert not a.overlaps(b)


def test_online_meetings_never_conflict():
    a = Meeting(online=True)
    b = Meeting(("M",), time(9, 0), time(10, 0))
    assert not a.overlaps(b)


def test_section_conflict_detection():
    first = section(meetings=[Meeting(("M", "W"), time(13, 0), time(13, 50))])
    second = section(code="CSCI 361", meetings=[Meeting(("W",), time(13, 30), time(14, 20))])
    third = section(code="MATH 251", meetings=[Meeting(("F",), time(13, 0), time(13, 50))])
    assert first.conflicts_with(second)
    assert not first.conflicts_with(third)


def test_continuation_row_detection():
    cells = [""] * 15
    cells[9], cells[10] = "F", "11:00 AM-12:15 PM"
    assert is_continuation(cells)
    cells[2] = "BIOL 355"
    assert not is_continuation(cells)


def test_merge_keeps_one_record_per_section():
    # одна секция напечатана дважды: онлайн-лекция и очная
    online = section(meetings=[Meeting(online=True)], enrolled=627, capacity=637)
    onsite = section(meetings=[Meeting(("F",), time(12, 0), time(12, 50))], enrolled=627, capacity=637)
    merged = merge_sections([online, onsite])
    assert len(merged) == 1
    assert len(merged[0].meetings) == 2
    assert merged[0].enrolled == 627


def test_merge_takes_larger_enrollment_on_mismatch():
    merged = merge_sections([section(enrolled=37), section(enrolled=38)])
    assert merged[0].enrolled == 38


def test_demand_counts_lectures_only():
    # студент лекции числится и в лаборатории — суммировать всё значит задвоить
    snapshot = Snapshot(
        term="Fall 2026",
        taken_at=None,
        sections=[
            section(label="1L", enrolled=70, capacity=72),
            section(label="2L", enrolled=50, capacity=72),
            section(label="1Lb", enrolled=30, capacity=36),
            section(label="1T", enrolled=70, capacity=72),
        ],
    )
    demand = snapshot.demand()["CSCI 341"]
    assert (demand.sections, demand.enrolled, demand.capacity) == (2, 120, 144)


def test_demand_falls_back_when_no_lectures():
    snapshot = Snapshot("Fall 2026", None, [section(label="1Int", enrolled=20, capacity=50)])
    assert snapshot.demand()["CSCI 341"].enrolled == 20


def test_demand_flags_full_course():
    snapshot = Snapshot("Fall 2026", None, [section(label="1L", enrolled=73, capacity=60)])
    demand = snapshot.demand()["CSCI 341"]
    assert demand.is_full and demand.seats_left == -13


def test_filter_level_keeps_undergraduates():
    snapshot = Snapshot(
        "Spring 2026",
        None,
        [section(level="UG"), section(code="X 500", level="PhD"), section(code="Y 600", level="GrM")],
    )
    assert [s.code for s in snapshot.filter_level("UG").sections] == ["CSCI 341"]


def test_pre_registration_snapshot_detected():
    empty = Snapshot("Fall 2025", None, [section(enrolled=0), section(code="X 101", enrolled=0)])
    started = Snapshot("Fall 2025", None, [section(enrolled=0), section(code="X 101", enrolled=5)])
    assert empty.is_pre_registration
    assert not started.is_pre_registration
