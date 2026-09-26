"""Релевантность: о чём курс и что заходит этому студенту.

Из тридцати семи технических элективов все закрывают одну и ту же позицию и
дают одни и те же кредиты. По нужности они неразличимы, и без понимания
содержания выбор сваливался на остаточный признак — куда легче попасть.

Здесь курсы и студент попадают в одно пространство. Текст курса — название и
описание из каталога Registrar — превращается в вектор так, что близкие по
смыслу курсы оказываются рядом. Профиль студента складывается из векторов
пройденных курсов с весом по оценке: то, где он силён, тянет профиль сильнее.
Близость профиля к курсу и есть релевантность.

Ничего здесь не обучается на наших данных. Веса TF-IDF считаются по самому
каталогу, а модель эмбеддингов приходит готовой. Поэтому слой работает с
первого дня и с единственным транскриптом — студенты для него не нужны.

Чего здесь нет — проверки. У модели заполняемости был эталон и три семестра,
на которых она его била. Здесь эталона не существует: "хорошая ли это
рекомендация" нельзя посчитать, пока не видно, что студенты выбирают на самом
деле. Поэтому вес релевантности в общей формуле намеренно невелик, а TF-IDF
оставлен как базовый способ — если эмбеддинги его не перевешивают на глаз,
тяжёлую зависимость ставить незачем.

    uv run python -m course_recommender.models.embeddings \\
      --transcript student_transcript.pdf --descriptions data/processed/descriptions.json
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..domain import Student

TFIDF = "tfidf"
GRADE_SCALE = 4.0
# Два способа мерить близость студента к курсу.
CENTROID = "centroid"
NEAREST = "nearest"


@dataclass
class CourseVectors:
    """Курсы в векторном пространстве."""

    codes: tuple[str, ...] = ()
    matrix: np.ndarray | None = None
    backend: str = TFIDF
    # Словарь признаков — только у TF-IDF, для объяснения "почему похоже".
    features: tuple[str, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.codes)

    @property
    def index(self) -> dict[str, int]:
        return {code: position for position, code in enumerate(self.codes)}

    def vector_of(self, code: str) -> np.ndarray | None:
        position = self.index.get(code)
        return None if position is None else self.matrix[position]

    def similarity(self, profile: np.ndarray | None) -> dict[str, float]:
        """Близость каждого курса к профилю, от 0 до 1.

        Косинус приведён из [-1, 1] в [0, 1]: отрицательная близость значит
        "про другое", а не "вредно", и отрицательных весов в формуле полезности
        быть не должно.
        """
        if profile is None or self.matrix is None or not len(self):
            return {}
        raw = self.matrix @ profile
        return {code: float((value + 1.0) / 2.0) for code, value in zip(self.codes, raw)}


def _normalize(matrix: np.ndarray) -> np.ndarray:
    """Привести строки к единичной длине, чтобы скалярное произведение было косинусом."""
    lengths = np.linalg.norm(matrix, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return matrix / lengths


def _center(matrix: np.ndarray) -> np.ndarray:
    """Убрать из векторов то, что общее у всех курсов.

    Языковая модель сажает любые два текста близко друг к другу: у курсов
    каталога косинус случайной пары около 0.85, и на этом фоне разница между
    "про машинное обучение" и "про этику" теряется. Вычитание среднего по
    каталогу убирает общую составляющую — остаётся то, чем курсы отличаются.
    Для TF-IDF это не нужно: там вектора разрежены и уже почти ортогональны.
    """
    return matrix - matrix.mean(axis=0)


def build_tfidf(texts: dict[str, str]) -> CourseVectors:
    """Векторы по словам самого каталога.

    Базовый способ: считает, какие слова для курса характерны на фоне
    остальных. Синонимов он не знает — "neural networks" и "deep learning"
    для него разное, — но зависимостей не требует и объясним: у каждого
    измерения есть имя.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    codes = tuple(texts)
    if not codes:
        return CourseVectors()
    vectorizer = TfidfVectorizer(
        stop_words="english", ngram_range=(1, 2), sublinear_tf=True, min_df=1
    )
    matrix = vectorizer.fit_transform([texts[code] for code in codes]).toarray()
    return CourseVectors(
        codes=codes,
        matrix=_normalize(matrix),
        backend=TFIDF,
        features=tuple(vectorizer.get_feature_names_out()),
    )


def build_embeddings(texts: dict[str, str], model: str | None = None) -> CourseVectors:
    """Векторы готовой языковой моделью.

    Она знает, что "deep learning" и "neural networks" про одно, — этого
    TF-IDF не умеет. Взамен тянет torch, поэтому вынесена в отдельный extra.
    """
    from sentence_transformers import SentenceTransformer

    from ..config import EMBEDDING_MODEL

    name = model or EMBEDDING_MODEL
    codes = tuple(texts)
    if not codes:
        return CourseVectors(backend=name)
    encoder = SentenceTransformer(name)
    matrix = np.asarray(encoder.encode([_prepare(texts[code], name) for code in codes]))
    return CourseVectors(codes=codes, matrix=_normalize(_center(matrix)), backend=name)


def _prepare(text: str, model: str) -> str:
    """Текст в том виде, в каком его ждёт модель.

    Семейство e5 обучено на парах с пометкой, что есть что, и без префикса
    выдаёт заметно худшую близость. Курсы здесь сравниваются друг с другом,
    поэтому все они "passage".
    """
    return f"passage: {text}" if "e5" in model.lower() else text


def build(texts: dict[str, str], backend: str = TFIDF) -> CourseVectors:
    """Собрать векторы выбранным способом."""
    return build_tfidf(texts) if backend == TFIDF else build_embeddings(texts, backend)


def cache_path(backend: str) -> Path:
    from ..config import DATA_PROCESSED

    name = re.sub(r"[^a-z0-9]+", "-", backend.lower()).strip("-")
    return DATA_PROCESSED / f"vectors-{name}.npz"


def save(vectors: CourseVectors, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        codes=np.array(vectors.codes),
        matrix=vectors.matrix,
        backend=np.array(vectors.backend),
        features=np.array(vectors.features),
    )


def load(path: Path) -> CourseVectors:
    stored = np.load(path, allow_pickle=False)
    return CourseVectors(
        codes=tuple(stored["codes"].tolist()),
        matrix=stored["matrix"],
        backend=str(stored["backend"]),
        features=tuple(stored["features"].tolist()),
    )


def cached(texts: dict[str, str], backend: str = TFIDF, path: Path | None = None) -> CourseVectors:
    """Векторы из кеша, а если его нет — посчитать и сохранить.

    Языковая модель кодирует две тысячи описаний минуты, и делать это на
    каждый запуск незачем. Кеш привязан к составу каталога: изменился
    список курсов — считаем заново.
    """
    path = path or cache_path(backend)
    if path.exists():
        stored = load(path)
        if set(stored.codes) == set(texts):
            return stored
    vectors = build(texts, backend)
    if len(vectors):
        save(vectors, path)
    return vectors


def grade_weight(grade: float | None) -> float:
    """Вклад пройденного курса в профиль.

    Оценка по шкале GPA, приведённая к долям: отличный курс тянет профиль
    вдвое сильнее, чем сданный на C. Провал и незачёт не тянут вовсе —
    сказать, что студенту это близко, они не дают оснований.
    """
    if grade is None or grade <= 0:
        return 0.0
    return min(1.0, grade / GRADE_SCALE)


def student_profile(student: Student, vectors: CourseVectors) -> np.ndarray | None:
    """Профиль студента: пройденные курсы с весом по оценке.

    None означает, что профиль построить не из чего: ни одного пройденного
    курса в каталоге не нашлось. Это не повод подставлять нули — курс без
    профиля просто не получает оценки релевантности.
    """
    if vectors.matrix is None or not len(vectors):
        return None

    index = vectors.index
    total = np.zeros(vectors.matrix.shape[1])
    weighted = 0.0
    for completed in student.completed:
        position = index.get(completed.code)
        weight = grade_weight(completed.grade)
        if position is None or not weight:
            continue
        total += vectors.matrix[position] * weight
        weighted += weight

    if not weighted:
        return None
    profile = total / weighted
    length = float(np.linalg.norm(profile))
    return None if length == 0 else profile / length


@dataclass(frozen=True)
class Affinity:
    """Насколько курс близок студенту и из-за чего."""

    code: str
    score: float
    closest: str = ""

    @property
    def is_known(self) -> bool:
        return bool(self.closest)


def affinities(
    student: Student, vectors: CourseVectors, mode: str = NEAREST
) -> dict[str, Affinity]:
    """Близость каждого курса к студенту.

    Два способа, и по умолчанию второй. "centroid" считает близость к
    среднему по всему пройденному — но усреднение тридцати курсов даёт
    размытый портрет "среднего студента специальности", и все кандидаты
    оказываются от него примерно одинаково далеко.

    "nearest" ищет самый похожий из пройденных и берёт его: курс релевантен,
    если он похож на то, что студенту уже зашло. Различает кандидатов заметно
    лучше и вдобавок объясним — видно, на что именно похоже.
    """
    if vectors.matrix is None or not len(vectors):
        return {}

    if mode == CENTROID:
        scores = vectors.similarity(student_profile(student, vectors))
        return {code: Affinity(code=code, score=score) for code, score in scores.items()}

    index = vectors.index
    taken = [
        (completed.code, index[completed.code], grade_weight(completed.grade))
        for completed in student.completed
        if completed.code in index and grade_weight(completed.grade)
    ]
    if not taken:
        return {}

    found: dict[str, Affinity] = {}
    for position, code in enumerate(vectors.codes):
        vector = vectors.matrix[position]
        # Сначала ищем самый похожий пройденный курс — по смыслу, без оглядки
        # на оценку. Иначе в объяснении окажется не похожий курс, а тот, где
        # оценка выше: у языковой модели близости куда ровнее, чем оценки, и
        # произведение вытаскивало бы наверх один и тот же отличный курс.
        best_similarity, best_code, best_weight = 0.0, "", 0.0
        for source, source_position, weight in taken:
            similarity = float(vector @ vectors.matrix[source_position])
            if similarity > best_similarity:
                best_similarity, best_code, best_weight = similarity, source, weight
        found[code] = Affinity(
            code=code, score=best_similarity * best_weight, closest=best_code
        )
    return found


def relevance(
    student: Student, vectors: CourseVectors, mode: str = NEAREST
) -> dict[str, float]:
    """Насколько каждый курс каталога близок этому студенту."""
    return {code: found.score for code, found in affinities(student, vectors, mode).items()}


def rescale(scores: dict[str, float]) -> dict[str, float]:
    """Привести близости к долям от лучшей в наборе.

    Сами по себе косинусы малы и в формулу полезности не ложатся: важно не
    абсолютное значение, а насколько кандидат хуже лучшего из доступных.
    Когда все кандидаты похожи между собой, доли остаются близки к единице —
    это и значит, что выбирать по релевантности здесь не из чего.
    """
    best = max(scores.values(), default=0.0)
    if best <= 0:
        return dict.fromkeys(scores, 0.0)
    return {code: value / best for code, value in scores.items()}


def explain(code: str, vectors: CourseVectors, profile: np.ndarray, top: int = 5) -> list[str]:
    """Слова, по которым курс похож на профиль. Только для TF-IDF.

    У эмбеддингов измерения имён не имеют, и объяснить близость теми же
    словами нельзя — поэтому здесь пусто, а не выдуманный список.
    """
    vector = vectors.vector_of(code)
    if vector is None or not vectors.features or profile is None:
        return []
    contribution = vector * profile
    best = np.argsort(contribution)[::-1][:top]
    return [vectors.features[position] for position in best if contribution[position] > 0]


def main() -> None:
    import argparse
    from pathlib import Path

    from ..data.descriptions import default_path
    from ..data.descriptions import load as load_descriptions
    from ..data.transcripts import parse_pdf as parse_transcript

    parser = argparse.ArgumentParser(description="Что близко этому студенту по содержанию")
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--descriptions", type=Path, default=None)
    parser.add_argument("--backend", default=TFIDF, help="tfidf или имя модели эмбеддингов")
    parser.add_argument("--no-cache", action="store_true", help="пересчитать, не читая кеш")
    parser.add_argument("--mode", default=NEAREST, choices=(NEAREST, CENTROID))
    parser.add_argument("--top", type=int, default=12)
    parser.add_argument("--subject", help="ограничить префиксом, например CSCI")
    args = parser.parse_args()

    catalog = load_descriptions(args.descriptions or default_path())
    texts = catalog.texts(catalog.undergraduate)
    vectors = build(texts, args.backend) if args.no_cache else cached(texts, args.backend)
    student = parse_transcript(args.transcript).student()

    found = affinities(student, vectors, args.mode)
    if not found:
        print("профиль не построить: ни один пройденный курс не найден в каталоге")
        return

    profile = student_profile(student, vectors)
    taken = student.completed_codes
    scores = rescale({code: value.score for code, value in found.items()})
    ranked = sorted(
        (
            (score, code)
            for code, score in scores.items()
            if code not in taken and (not args.subject or code.startswith(args.subject))
        ),
        reverse=True,
    )

    print(f"способ: {vectors.backend} ({args.mode}), курсов в пространстве: {len(vectors)}")
    print(f"профиль собран из {len(taken & set(vectors.codes))} пройденных курсов\n")
    for score, code in ranked[: args.top]:
        course = catalog.get(code)
        title = course.title if course else ""
        closest = found[code].closest
        print(f"  {score:.2f}  {code:10s} {title[:44]:46s}" + (f"похож на {closest}" if closest else ""))
        words = explain(code, vectors, profile)
        if words:
            print(f"        по словам: {', '.join(words)}")


if __name__ == "__main__":
    main()
