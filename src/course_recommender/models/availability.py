"""Вероятность того, что курс заполнится.

Раньше этот вопрос решался правилом: заполнился в прошлый раз — значит
заполнится и теперь. Правило даёт 0 или 1, а решение, которое на нём строится,
вероятностное, и жёсткая единица там врёт дважды — и когда курс всё же не
заполнился, и когда заполнился, но еле-еле.

Что здесь измеряется и что нет. Выгрузки расписания дают Enr и Cap, то есть
спрос на курс целиком. Кому именно досталось место, в них нет, поэтому
персональную вероятность отсюда получить нельзя ни одной моделью. Обучается
ровно то, что данные поддерживают: заполнится ли курс. Как между собой делят
места при заполнении, остаётся предположением, и оно вынесено в recommend.py
отдельной таблицей — так видно, где кончается измеренное.

Модель намеренно маленькая: логистическая регрессия на двух признаках истории.
Это не экономия, а результат проверки. Бустинг на четырнадцати признаках
выигрывает на одном семестре и заметно проигрывает на другом, где обучающих
строк меньше: на 1808 наблюдениях сложная модель неустойчива. Двухпризнаковая
регрессия одинаково хороша на обоих срезах, и её выбрали поэтому.

    uv run python -m course_recommender.models.availability --schedule *.pdf
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..data.catalog import term_key
from ..data.schedule import CourseHistory, Snapshot

# Признаки — оба из одного источника, расписания. Больше признаков проверяли,
# устойчивого выигрыша они не дали.
FEATURES = ("mean_fill", "ever_full")
FULL = 1.0


@dataclass(frozen=True)
class Observation:
    """Курс в одном семестре: что было известно до регистрации и что вышло."""

    code: str
    term: str
    fill_rate: float
    # Признаки посчитаны строго по предыдущим семестрам: иначе модель
    # подглядывает в ответ и на новом семестре разваливается.
    mean_fill: float | None = None
    last_fill: float | None = None
    ever_full: bool = False
    terms_seen: int = 0

    @property
    def is_full(self) -> bool:
        return self.fill_rate >= FULL

    @property
    def has_history(self) -> bool:
        return self.terms_seen > 0

    @property
    def features(self) -> list[float]:
        return [self.mean_fill or 0.0, float(self.ever_full)]


def latest_snapshots(snapshots: list[Snapshot]) -> dict[str, Snapshot]:
    """Последний снимок каждого семестра, уже после открытия регистрации."""
    latest: dict[str, Snapshot] = {}
    for snapshot in snapshots:
        if snapshot.is_pre_registration or not snapshot.sections:
            continue
        current = latest.get(snapshot.term)
        if current is None or (
            snapshot.taken_at and current.taken_at and snapshot.taken_at > current.taken_at
        ):
            latest[snapshot.term] = snapshot
    return latest


def observations(snapshots: list[Snapshot], kinds: tuple[str, ...] = ("L",)) -> list[Observation]:
    """Разложить снимки в наблюдения "курс × семестр" с историей на тот момент.

    Порядок семестров здесь календарный, а не по времени выгрузки: важно, что
    было известно к началу регистрации, а не когда скачали файл.
    """
    latest = latest_snapshots(snapshots)
    terms = sorted(latest, key=term_key)

    seen: dict[str, list[float]] = {}
    rows: list[Observation] = []
    for term in terms:
        current = {
            code: demand.fill_rate
            for code, demand in latest[term].demand(kinds).items()
            if demand.fill_rate is not None
        }
        for code, rate in current.items():
            past = seen.get(code, [])
            rows.append(
                Observation(
                    code=code,
                    term=term,
                    fill_rate=rate,
                    mean_fill=sum(past) / len(past) if past else None,
                    last_fill=past[-1] if past else None,
                    ever_full=any(value >= FULL for value in past),
                    terms_seen=len(past),
                )
            )
        for code, rate in current.items():
            seen.setdefault(code, []).append(rate)
    return rows


@dataclass
class AvailabilityModel:
    """Логистическая регрессия: заполнится ли курс.

    Коэффициенты хранятся прямо здесь, а не в pickle: модель из трёх чисел
    должна читаться глазами, иначе непонятно, чему она научилась.
    """

    intercept: float = 0.0
    coefficients: list[float] = field(default_factory=list)
    means: list[float] = field(default_factory=list)
    scales: list[float] = field(default_factory=list)
    trained_on: tuple[str, ...] = ()
    samples: int = 0

    @property
    def is_fitted(self) -> bool:
        return bool(self.coefficients)

    def fit(self, rows: list[Observation]) -> AvailabilityModel:
        """Обучить на наблюдениях, у которых есть история."""
        from sklearn.linear_model import LogisticRegression

        usable = [row for row in rows if row.has_history]
        if len(usable) < 2 or len({row.is_full for row in usable}) < 2:
            raise ValueError("для обучения нужны наблюдения обоих исходов")

        columns = list(zip(*(row.features for row in usable)))
        self.means = [sum(column) / len(column) for column in columns]
        self.scales = [_stdev(column, mean) for column, mean in zip(columns, self.means)]

        features = [self._scaled(row.features) for row in usable]
        target = [int(row.is_full) for row in usable]
        model = LogisticRegression(max_iter=1000).fit(features, target)

        self.intercept = float(model.intercept_[0])
        self.coefficients = [float(value) for value in model.coef_[0]]
        self.trained_on = tuple(sorted({row.term for row in usable}, key=term_key))
        self.samples = len(usable)
        return self

    def _scaled(self, values: list[float]) -> list[float]:
        return [
            (value - mean) / scale
            for value, mean, scale in zip(values, self.means, self.scales)
        ]

    def probability(self, mean_fill: float, ever_full: bool) -> float:
        """Вероятность, что курс заполнится."""
        if not self.is_fitted:
            raise ValueError("модель не обучена")
        scaled = self._scaled([mean_fill, float(ever_full)])
        total = self.intercept + sum(c * v for c, v in zip(self.coefficients, scaled))
        return 1.0 / (1.0 + math.exp(-total))

    def predict_one(self, row: Observation) -> float:
        """Вероятность по уже посчитанным признакам наблюдения."""
        return self.probability(row.mean_fill or 0.0, row.ever_full)

    def predict(self, history: CourseHistory | None) -> float | None:
        """Вероятность по истории курса. None — истории нет, и гадать не о чем."""
        if history is None or not history.observations or not self.is_fitted:
            return None
        return self.probability(history.mean_fill, history.ever_full)

    def to_json(self) -> dict:
        return {
            "features": list(FEATURES),
            "intercept": self.intercept,
            "coefficients": self.coefficients,
            "means": self.means,
            "scales": self.scales,
            "trained_on": list(self.trained_on),
            "samples": self.samples,
        }

    @classmethod
    def from_json(cls, payload: dict) -> AvailabilityModel:
        return cls(
            intercept=payload["intercept"],
            coefficients=list(payload["coefficients"]),
            means=list(payload["means"]),
            scales=list(payload["scales"]),
            trained_on=tuple(payload.get("trained_on", ())),
            samples=payload.get("samples", 0),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")

    def describe(self) -> str:
        weights = ", ".join(
            f"{name} {value:+.2f}" for name, value in zip(FEATURES, self.coefficients)
        )
        terms = ", ".join(self.trained_on)
        return f"{weights}; обучена на {self.samples} наблюдениях ({terms})"


def load(path: Path) -> AvailabilityModel:
    return AvailabilityModel.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def _stdev(values, mean: float) -> float:
    variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
    return math.sqrt(variance) or 1.0


def training_rows(rows: list[Observation], before: str | None = None) -> list[Observation]:
    """Наблюдения, пригодные для обучения к этому семестру.

    Целевой семестр не попадает: его исход как раз и предсказывают, и держать
    его в обучающей выборке значило бы проверять модель по ответу. Первый
    семестр выборки не годится и сам по себе — истории до него нет.
    """
    usable = [r for r in rows if before is None or term_key(r.term) < term_key(before)]
    return [row for row in usable if row.has_history]


def can_train(rows: list[Observation], before: str | None = None) -> bool:
    """Хватает ли данных: нужны оба исхода, иначе учить нечему."""
    usable = training_rows(rows, before)
    return len(usable) >= 2 and len({row.is_full for row in usable}) == 2


def train(rows: list[Observation], before: str | None = None) -> AvailabilityModel:
    """Обучить на всём, что было известно до этого семестра."""
    return AvailabilityModel().fit(training_rows(rows, before))


def brier(actual: list[int], predicted: list[float]) -> float:
    """Средний квадрат ошибки вероятности — цена плохой калибровки."""
    return sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual)


def auc(actual: list[int], predicted: list[float]) -> float:
    """Площадь под ROC: насколько верно модель упорядочивает курсы по риску."""
    positives = [p for a, p in zip(actual, predicted) if a]
    negatives = [p for a, p in zip(actual, predicted) if not a]
    if not positives or not negatives:
        return float("nan")
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives
    )
    return wins / (len(positives) * len(negatives))


def accuracy(actual: list[int], predicted: list[float], threshold: float = 0.5) -> float:
    return sum(
        float((p >= threshold) == bool(a)) for a, p in zip(actual, predicted)
    ) / len(actual)


def evaluate(rows: list[Observation], term: str) -> dict[str, dict[str, float]]:
    """Сравнить модель с эталонами на одном семестре.

    Эталонов два, и оба честные. Первый — правило, по которому система живёт
    сейчас: "в прошлый раз заполнился — заполнится". Второй — та же история,
    но переведённая в вероятность: без него сравнение было бы нечестным, ведь
    выигрыш модели в калибровке достался бы ей даром.
    """
    test = [row for row in rows if row.term == term and row.has_history]
    if not test or not can_train(rows, term):
        return {}
    actual = [int(row.is_full) for row in test]

    model = train(rows, before=term)
    scores = {
        "модель": [model.predict_one(row) for row in test],
        "эталон сейчас: заполнялся полностью": [float(row.ever_full) for row in test],
        "эталон: среднее заполнение ≥ 100%": [float((row.mean_fill or 0) >= FULL) for row in test],
        "константа: доля полных": [sum(actual) / len(actual)] * len(test),
    }
    return {
        name: {
            "auc": auc(actual, values),
            "brier": brier(actual, values),
            "accuracy": accuracy(actual, values),
            "n": len(test),
        }
        for name, values in scores.items()
    }


def main() -> None:
    import argparse

    from ..config import DATA_PROCESSED
    from ..data.schedule import parse_pdf

    parser = argparse.ArgumentParser(description="Обучить и проверить модель заполняемости")
    parser.add_argument("schedule", type=Path, nargs="+", help="PDF расписаний с Enr/Cap")
    parser.add_argument(
        "-o", "--output", type=Path, default=DATA_PROCESSED / "availability.json"
    )
    args = parser.parse_args()

    snapshots = [parse_pdf(path).filter_level("UG") for path in args.schedule]
    rows = observations(snapshots)
    terms = sorted({row.term for row in rows}, key=term_key)
    print(f"наблюдений: {len(rows)}, семестров: {len(terms)} ({', '.join(terms)})")

    for term in terms[1:]:
        metrics = evaluate(rows, term)
        if not metrics:
            continue
        first = next(iter(metrics.values()))
        print(f"\n--- проверка на {term} ({first['n']} курсов с историей)")
        for name, value in metrics.items():
            print(
                f"   {name:38s} AUC {value['auc']:.3f}  Brier {value['brier']:.3f}  "
                f"точность {value['accuracy']:.0%}"
            )

    model = train(rows)
    print(f"\nитоговая модель: {model.describe()}")
    model.save(args.output)
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
