import numpy as np

from course_recommender.domain import CompletedCourse, Student
from course_recommender.models.embeddings import (
    CENTROID,
    NEAREST,
    CourseVectors,
    affinities,
    build_tfidf,
    explain,
    grade_weight,
    relevance,
    rescale,
    student_profile,
)

CATALOG = {
    "CS 101": "Machine Learning. Training neural networks on data to make predictions.",
    "CS 102": "Deep Learning. Neural networks with many layers trained on large data.",
    "PHIL 210": "Ethics. Moral philosophy, virtue, justice and the good life.",
    "HST 100": "History of Kazakhstan. Steppe empires, colonial period and independence.",
}


def student(*taken):
    return Student("s1", "CS", 3, 3.0, [CompletedCourse(code, grade, 1) for code, grade in taken])


def test_similar_texts_end_up_close_together():
    vectors = build_tfidf(CATALOG)
    ml, deep, ethics = (vectors.vector_of(c) for c in ("CS 101", "CS 102", "PHIL 210"))
    assert float(ml @ deep) > float(ml @ ethics)


def test_empty_catalog_gives_empty_space():
    vectors = build_tfidf({})
    assert len(vectors) == 0
    assert vectors.similarity(np.array([1.0])) == {}


def test_grade_weight_scales_with_the_grade():
    assert grade_weight(4.0) == 1.0
    assert grade_weight(2.0) == 0.5
    # Провал и незачёт не говорят, что студенту это близко
    assert grade_weight(0.0) == 0.0
    assert grade_weight(None) == 0.0


def test_profile_is_pulled_by_the_courses_that_went_well():
    vectors = build_tfidf(CATALOG)
    good_at_ml = student(("CS 101", 4.0), ("PHIL 210", 1.0))
    scores = vectors.similarity(student_profile(good_at_ml, vectors))
    assert scores["CS 102"] > scores["HST 100"]


def test_profile_is_none_when_nothing_matches_the_catalog():
    vectors = build_tfidf(CATALOG)
    assert student_profile(student(("XX 999", 4.0)), vectors) is None
    assert relevance(student(("XX 999", 4.0)), vectors) == {}


def test_nearest_mode_names_the_course_it_matched():
    vectors = build_tfidf(CATALOG)
    found = affinities(student(("CS 101", 4.0)), vectors)
    assert found["CS 102"].closest == "CS 101"
    assert found["CS 102"].score > found["HST 100"].score
    assert found["CS 102"].is_known


def test_centroid_mode_gives_no_explanation():
    vectors = build_tfidf(CATALOG)
    found = affinities(student(("CS 101", 4.0)), vectors, mode=CENTROID)
    assert found["CS 102"].closest == ""
    assert not found["CS 102"].is_known


def test_nearest_mode_discriminates_better_than_the_average():
    vectors = build_tfidf(CATALOG)
    person = student(("CS 101", 4.0), ("HST 100", 3.0), ("PHIL 210", 3.0))
    def spread(mode):
        scores = [found.score for found in affinities(person, vectors, mode).values()]
        return max(scores) - min(scores)

    assert spread(NEAREST) > spread(CENTROID)


def test_rescale_turns_scores_into_shares_of_the_best():
    assert rescale({"a": 0.2, "b": 0.1}) == {"a": 1.0, "b": 0.5}
    # Когда близости нет ни у кого, выбирать по ней не из чего
    assert rescale({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}
    assert rescale({}) == {}


def test_similarity_never_goes_negative():
    vectors = build_tfidf(CATALOG)
    profile = -vectors.vector_of("PHIL 210")
    assert all(0.0 <= value <= 1.0 for value in vectors.similarity(profile).values())


def test_explain_names_the_shared_words():
    vectors = build_tfidf(CATALOG)
    profile = student_profile(student(("CS 101", 4.0)), vectors)
    words = explain("CS 102", vectors, profile)
    assert "neural" in " ".join(words)


def test_explain_is_silent_without_a_vocabulary():
    # У эмбеддингов измерения имён не имеют — выдумывать слова нельзя
    vectors = CourseVectors(codes=("CS 101",), matrix=np.ones((1, 3)), backend="model")
    assert explain("CS 101", vectors, np.ones(3)) == []
