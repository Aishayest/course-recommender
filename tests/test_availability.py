from datetime import UTC, datetime

import pytest

from course_recommender.data.schedule import CourseHistory, Section, Snapshot
from course_recommender.models.availability import (
    AvailabilityModel,
    accuracy,
    auc,
    brier,
    can_train,
    evaluate,
    observations,
    train,
    training_rows,
)


def snapshot(term, fills, taken_at=None):
    """Снимок семестра: код курса -> заполняемость."""
    return Snapshot(
        term=term,
        taken_at=taken_at,
        sections=[
            Section(term=term, code=code, section="1L", enrolled=int(rate * 100), capacity=100)
            for code, rate in fills.items()
        ],
    )


def test_observations_look_only_at_earlier_terms():
    rows = observations(
        [
            snapshot("Fall 2025", {"CSCI 151": 0.8}),
            snapshot("Spring 2026", {"CSCI 151": 1.2}),
            snapshot("Fall 2026", {"CSCI 151": 1.0}),
        ]
    )
    by_term = {row.term: row for row in rows}

    # У первого семестра истории нет вовсе
    assert by_term["Fall 2025"].terms_seen == 0
    assert by_term["Fall 2025"].mean_fill is None
    # Второй знает только про первый, а не про свой собственный исход
    assert by_term["Spring 2026"].mean_fill == 0.8
    assert by_term["Spring 2026"].ever_full is False
    assert by_term["Fall 2026"].mean_fill == pytest.approx(1.0)
    assert by_term["Fall 2026"].ever_full is True


def test_observations_order_terms_by_calendar_not_by_download_time():
    # Осенний файл скачали раньше весеннего, но семестр всё равно позже
    rows = observations(
        [
            snapshot("Fall 2026", {"CSCI 151": 1.5}, taken_at=datetime(2026, 1, 1, tzinfo=UTC)),
            snapshot("Spring 2026", {"CSCI 151": 0.5}, taken_at=datetime(2026, 9, 1, tzinfo=UTC)),
        ]
    )
    fall = next(row for row in rows if row.term == "Fall 2026")
    assert fall.mean_fill == 0.5


def test_observations_skip_snapshots_taken_before_registration():
    rows = observations(
        [
            snapshot("Fall 2025", {"CSCI 151": 0.0}),  # регистрация ещё не открыта
            snapshot("Spring 2026", {"CSCI 151": 0.9}),
        ]
    )
    assert [row.term for row in rows] == ["Spring 2026"]
    assert rows[0].terms_seen == 0


def test_observation_is_full_at_hundred_percent():
    rows = observations([snapshot("Fall 2026", {"A 101": 1.0, "B 101": 0.99})])
    full = {row.code: row.is_full for row in rows}
    assert full == {"A 101": True, "B 101": False}


def test_training_rows_drop_the_target_term_and_courses_without_history():
    rows = observations(
        [
            snapshot("Fall 2025", {"A 101": 1.2}),
            snapshot("Spring 2026", {"A 101": 0.5}),
            snapshot("Fall 2026", {"A 101": 1.1}),
        ]
    )
    usable = training_rows(rows, before="Fall 2026")
    assert [row.term for row in usable] == ["Spring 2026"]


def test_can_train_needs_both_outcomes():
    only_full = observations(
        [snapshot("Fall 2025", {"A 101": 1.2}), snapshot("Spring 2026", {"A 101": 1.3})]
    )
    assert not can_train(only_full)

    mixed = observations(
        [
            snapshot("Fall 2025", {"A 101": 1.2, "B 101": 0.3}),
            snapshot("Spring 2026", {"A 101": 1.3, "B 101": 0.2}),
        ]
    )
    assert can_train(mixed)


def test_model_gives_higher_probability_to_courses_that_kept_filling_up():
    rows = observations(
        [
            snapshot("Fall 2025", {f"FULL {i}": 1.4 for i in range(10)} | {f"FREE {i}": 0.3 for i in range(10)}),
            snapshot("Spring 2026", {f"FULL {i}": 1.5 for i in range(10)} | {f"FREE {i}": 0.2 for i in range(10)}),
        ]
    )
    model = train(rows)
    assert model.is_fitted
    assert model.probability(1.4, True) > model.probability(0.3, False)


def test_untrained_model_refuses_to_guess():
    with pytest.raises(ValueError):
        AvailabilityModel().probability(1.0, True)


def test_predict_needs_history():
    model = AvailabilityModel(intercept=0.0, coefficients=[1.0, 1.0], means=[1.0, 0.5], scales=[0.5, 0.5])
    assert model.predict(None) is None
    assert model.predict(CourseHistory("CSCI 151", "")) is None
    assert model.predict(CourseHistory("CSCI 151", "", (("Fall 2025", 1.2),))) > 0.5


def test_model_survives_saving_and_reading_back():
    model = AvailabilityModel(
        intercept=0.25, coefficients=[0.5, 0.6], means=[0.9, 0.4], scales=[0.3, 0.5],
        trained_on=("Fall 2025",), samples=120,
    )
    restored = AvailabilityModel.from_json(model.to_json())
    assert restored.probability(1.2, True) == model.probability(1.2, True)
    assert restored.trained_on == ("Fall 2025",)


def test_metrics_on_known_answers():
    assert auc([1, 0], [0.9, 0.1]) == 1.0
    assert auc([1, 0], [0.1, 0.9]) == 0.0
    assert auc([1, 0], [0.5, 0.5]) == 0.5
    assert brier([1, 0], [1.0, 0.0]) == 0.0
    assert accuracy([1, 0], [0.9, 0.1]) == 1.0


def test_evaluate_compares_model_with_the_rule_it_replaces():
    rows = observations(
        [
            snapshot("Fall 2025", {f"FULL {i}": 1.4 for i in range(10)} | {f"FREE {i}": 0.3 for i in range(10)}),
            snapshot("Spring 2026", {f"FULL {i}": 1.5 for i in range(10)} | {f"FREE {i}": 0.2 for i in range(10)}),
            snapshot("Fall 2026", {f"FULL {i}": 1.3 for i in range(10)} | {f"FREE {i}": 0.4 for i in range(10)}),
        ]
    )
    metrics = evaluate(rows, "Fall 2026")
    assert "модель" in metrics
    assert metrics["модель"]["n"] == 20
    # Эталон, который модель должна побить, считается на тех же данных
    assert "эталон сейчас: заполнялся полностью" in metrics


def test_evaluate_returns_nothing_without_enough_history():
    rows = observations([snapshot("Fall 2026", {"A 101": 1.0})])
    assert evaluate(rows, "Fall 2026") == {}
