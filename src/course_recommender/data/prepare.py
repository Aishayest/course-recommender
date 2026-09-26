"""Подготовка данных: разобрать источники один раз и сложить рядом.

Источники системы — это два десятка PDF: документы регистрации, расписания,
отчёты об оценках, плюс выгрузка handbook и каталог с сайта Registrar. Разбор
занимает минуты, и делать его на каждый запуск нельзя: приложение должно
стартовать за секунду и читать готовое.

Здесь одна команда, которая собирает всё, и один загрузчик, который всё
читает. Чего нет — того нет: каждый слой необязателен, и система работает без
него, просто без соответствующих свидетельств.

    uv run python -m course_recommender.data.prepare --sources ~/Downloads
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import catalog as catalog_data
from . import descriptions as descriptions_data
from . import grades as grades_data
from . import schedule as schedule_data

# Как называются исходные файлы у Registrar.
PATTERNS = {
    "requirements": "Course Requirements and Registration Priorities*.pdf",
    "schedule": "school_schedule_by_term*.pdf",
    "grades": "UG_Grade_Report_*.pdf",
}


@dataclass
class Prepared:
    """Всё разобранное, готовое к работе."""

    catalog: catalog_data.Catalog = field(default_factory=catalog_data.Catalog)
    schedules: list = field(default_factory=list)
    grades: dict = field(default_factory=dict)
    descriptions: descriptions_data.Descriptions = field(
        default_factory=descriptions_data.Descriptions
    )
    availability: object | None = None
    vectors: object | None = None

    @property
    def terms(self) -> tuple[str, ...]:
        """Семестры, про которые хоть что-то известно, от старых к новым."""
        found = set(self.catalog.terms) | {snapshot.term for snapshot in self.schedules}
        return tuple(sorted(found, key=catalog_data.term_key))

    @property
    def fill_history(self) -> dict:
        """История заполняемости курсов по снимкам расписаний."""
        return schedule_data.history(self.schedules)

    def sections(self, term: str | None = None) -> dict[str, list]:
        """Секции семестра по курсам: расписание для проверки времени.

        Берётся последний снимок нужного семестра — тот, что после открытия
        регистрации. До неё в снимке нули, и по нему ничего не видно.
        """
        latest = None
        for snapshot in self.schedules:
            if term is not None and snapshot.term != term:
                continue
            if snapshot.is_pre_registration:
                continue
            if latest is None or (
                snapshot.taken_at and latest.taken_at and snapshot.taken_at > latest.taken_at
            ):
                latest = snapshot
        return latest.by_course() if latest else {}


def sources(directory: Path, kind: str) -> list[Path]:
    """Исходные файлы одного вида в папке."""
    return sorted(directory.expanduser().glob(PATTERNS[kind]))


def build(
    directory: Path | None = None,
    requirements=(),
    schedules=(),
    reports=(),
    fetch_descriptions: bool = False,
    vectors_backend: str | None = None,
    with_instructors: bool = True,
    report=print,
) -> Prepared:
    """Разобрать источники и сохранить кеши.

    Передать можно либо папку, где лежат выгрузки Registrar, либо пути
    к файлам каждого вида по отдельности.
    """
    if directory is not None:
        requirements = requirements or sources(directory, "requirements")
        schedules = schedules or sources(directory, "schedule")
        reports = reports or sources(directory, "grades")

    prepared = Prepared()

    if requirements:
        prepared.catalog = catalog_data.from_pdfs(requirements)
        catalog_data.save(prepared.catalog, catalog_data.default_path())
        report(f"каталог: {len(prepared.catalog)} курсов, {len(prepared.catalog.terms)} семестров")

    if schedules:
        prepared.schedules = [schedule_data.parse_pdf(path) for path in schedules]
        schedule_data.save(prepared.schedules, schedule_data.default_path())
        sections = sum(len(snapshot.sections) for snapshot in prepared.schedules)
        report(f"расписания: {len(prepared.schedules)} снимков, {sections} секций")

    if reports:
        rows = grades_data.read_reports(reports, schedules if with_instructors else ())
        grades_data.save(rows, grades_data.default_path())
        prepared.grades = grades_data.by_course(rows)
        named = sum(1 for row in rows if row.instructors)
        report(
            f"оценки: {len(rows)} секций, {len(prepared.grades)} курсов, "
            + (f"с преподавателем {named}" if with_instructors else "без имён преподавателей")
        )

    if fetch_descriptions:
        prepared.descriptions = descriptions_data.fetch_all()
        descriptions_data.save(prepared.descriptions, descriptions_data.default_path())
        described = sum(1 for c in prepared.descriptions.courses.values() if c.has_description)
        report(f"описания: {len(prepared.descriptions)} курсов, с описанием {described}")

    if prepared.schedules:
        from ..models import availability as availability_model

        rows = availability_model.observations(prepared.schedules)
        if availability_model.can_train(rows):
            prepared.availability = availability_model.train(rows)
            prepared.availability.save(availability_model_path())
            report(f"модель заполняемости: {prepared.availability.describe()}")
        else:
            report("модель заполняемости: данных не хватает, нужны оба исхода")

    if vectors_backend:
        from ..models import embeddings

        catalog = prepared.descriptions
        if not len(catalog) and descriptions_data.default_path().exists():
            catalog = descriptions_data.load(descriptions_data.default_path())
        prepared.vectors = embeddings.cached(
            catalog.texts(catalog.undergraduate), vectors_backend
        )
        report(f"векторы: {len(prepared.vectors)} курсов, способ {prepared.vectors.backend}")

    return prepared


def availability_model_path() -> Path:
    from ..config import DATA_PROCESSED

    return DATA_PROCESSED / "availability.json"


def load(vectors_backend: str | None = None) -> Prepared:
    """Прочитать всё, что подготовлено. Чего нет — того нет."""
    from ..models import availability as availability_model
    from ..models import embeddings

    prepared = Prepared()

    path = catalog_data.default_path()
    if path.exists():
        prepared.catalog = catalog_data.load(path)

    path = schedule_data.default_path()
    if path.exists():
        prepared.schedules = schedule_data.load(path)

    path = grades_data.default_path()
    if path.exists():
        prepared.grades = grades_data.load(path)

    path = descriptions_data.default_path()
    if path.exists():
        prepared.descriptions = descriptions_data.load(path)

    path = availability_model_path()
    if path.exists():
        prepared.availability = availability_model.load(path)

    if vectors_backend:
        path = embeddings.cache_path(vectors_backend)
        if path.exists():
            prepared.vectors = embeddings.load(path)

    return prepared


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Разобрать источники и сложить кеши")
    parser.add_argument(
        "--sources", type=Path, help="папка с выгрузками Registrar (PDF)"
    )
    parser.add_argument("--requirements", type=Path, nargs="*", default=[])
    parser.add_argument("--schedule", type=Path, nargs="*", default=[])
    parser.add_argument("--grades", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--descriptions", action="store_true", help="выгрузить описания с сайта Registrar"
    )
    parser.add_argument(
        "--vectors", nargs="?", const="tfidf", help="посчитать векторы: tfidf или имя модели"
    )
    parser.add_argument(
        "--no-instructors",
        action="store_true",
        help="не связывать оценки с именами преподавателей: для публичной выкладки",
    )
    args = parser.parse_args()

    if not any(
        (args.sources, args.requirements, args.schedule, args.grades, args.descriptions, args.vectors)
    ):
        parser.error("нечего разбирать: укажите --sources или файлы по видам")

    build(
        directory=args.sources,
        requirements=args.requirements,
        schedules=args.schedule,
        reports=args.grades,
        fetch_descriptions=args.descriptions,
        vectors_backend=args.vectors,
        with_instructors=not args.no_instructors,
    )


if __name__ == "__main__":
    main()
