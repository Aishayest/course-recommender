from dataclasses import replace
from datetime import UTC, date, datetime, time

from course_recommender.data.grades import SectionGrades
from course_recommender.data.grades import from_json as grades_from_json
from course_recommender.data.grades import to_json as grades_to_json
from course_recommender.data.prepare import PATTERNS, Prepared, sources
from course_recommender.data.schedule import Meeting, Section, Snapshot
from course_recommender.data.schedule import from_json as schedule_from_json
from course_recommender.data.schedule import to_json as schedule_to_json


def section(code="CSCI 341", label="1L", enrolled=30, capacity=40, days=("M", "W")):
    return Section(
        term="Fall 2026",
        code=code,
        section=label,
        title="Database Systems",
        school="SCAI",
        level="UG",
        credits_ects=6,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 11, 27),
        meetings=[Meeting(days=days, start=time(10, 30), end=time(11, 45))],
        enrolled=enrolled,
        capacity=capacity,
        faculty=("Кто-то",),
        room="Block 7",
        room_capacity=60,
    )


TAKEN_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def snapshot(term="Fall 2026", sections=None, enrolled=30, taken_at=TAKEN_AT):
    return Snapshot(
        term=term,
        taken_at=taken_at,
        sections=sections if sections is not None else [section(enrolled=enrolled)],
    )


def grades_row(code="CSCI 341", number=1, average=3.1):
    return SectionGrades(
        term="Fall 2025", school="SEDS", department="Computer Science", code=code,
        title=code, section=number, graded=40, average=average, deviation=0.6,
        median=3.0, shares={"A": 20.0, "W": 5.0}, letters=42, instructors=("Кто-то",),
    )


def test_schedule_survives_saving_and_reading_back():
    restored = schedule_from_json(schedule_to_json([snapshot()]))
    assert len(restored) == 1
    assert restored[0].term == "Fall 2026"
    assert restored[0].taken_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    back = restored[0].sections[0]
    # Секция знает, когда её выгрузили: отметка снимка проставляется каждой,
    # как и при разборе PDF
    assert back.taken_at == TAKEN_AT
    assert replace(back, taken_at=None) == snapshot().sections[0]
    # Время встреч и дни переживают запись — по ним проверяются пересечения
    assert back.meetings[0].days == ("M", "W")
    assert back.meetings[0].start == time(10, 30)
    assert back.start_date == date(2026, 8, 17)


def test_schedule_keeps_snapshot_without_a_timestamp():
    restored = schedule_from_json(schedule_to_json([snapshot(taken_at=None)]))
    assert restored[0].taken_at is None
    assert restored[0].sections[0].taken_at is None


def test_grades_survive_saving_and_reading_back():
    restored = grades_from_json(grades_to_json([grades_row()]))
    assert restored == [grades_row()]
    assert restored[0].shares["W"] == 5.0
    assert restored[0].instructors == ("Кто-то",)


def test_terms_come_from_every_source():
    prepared = Prepared(schedules=[snapshot("Fall 2026"), snapshot("Spring 2025")])
    # Порядок календарный, а не тот, в котором файлы попались
    assert prepared.terms == ("Spring 2025", "Fall 2026")


def test_sections_take_the_snapshot_made_after_registration_opened():
    before = snapshot(taken_at=datetime(2026, 7, 1, tzinfo=UTC), enrolled=0)
    after = snapshot(taken_at=datetime(2026, 9, 1, tzinfo=UTC), enrolled=30)
    prepared = Prepared(schedules=[before, after])

    sections = prepared.sections("Fall 2026")
    assert list(sections) == ["CSCI 341"]
    assert sections["CSCI 341"][0].enrolled == 30


def test_sections_are_empty_when_only_pre_registration_snapshots_exist():
    prepared = Prepared(schedules=[snapshot(enrolled=0)])
    assert prepared.sections("Fall 2026") == {}


def test_sections_ignore_other_terms():
    prepared = Prepared(schedules=[snapshot("Spring 2026")])
    assert prepared.sections("Fall 2026") == {}


def test_empty_prepared_has_nothing():
    prepared = Prepared()
    assert prepared.terms == ()
    assert prepared.sections() == {}
    assert prepared.fill_history == {}


def test_sources_finds_files_by_registrar_naming(tmp_path):
    (tmp_path / "school_schedule_by_term (3).pdf").touch()
    (tmp_path / "UG_Grade_Report_FA2025_SEDS_ver1.pdf").touch()
    (tmp_path / "отпускные фото.pdf").touch()

    assert [p.name for p in sources(tmp_path, "schedule")] == ["school_schedule_by_term (3).pdf"]
    assert len(sources(tmp_path, "grades")) == 1
    assert sources(tmp_path, "requirements") == []
    assert set(PATTERNS) == {"requirements", "schedule", "grades"}
