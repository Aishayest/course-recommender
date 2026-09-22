"""Каталог курсов университета из документов Course Requirements.

Документ Registrar выходит перед каждой регистрацией и описывает только свой
семестр. Пока разбирался один файл, у системы было слепое пятно: про весенние
курсы не было известно ничего — ни условий допуска, ни того, что они вообще
существуют, и приходилось подстраховываться позицией курса в плане.

Файлов же за 2023-2026 двенадцать, и вместе они дают каталог целиком: 1148
курсов, из них 559 не встречаются в осеннем документе вовсе. Это тот самый
каталог, без которого правила элективов ("любой курс CS 200+") не
разворачиваются в коды, а у весенних курсов не бывает пререквизитов.

Семестр остаётся частью ключа везде, где данные от него зависят. Пререквизиты
и тиры приоритета между семестрами меняются, и подставлять прошлогоднее в этот
семестр молча нельзя: каталог хранит их по семестрам и отдаёт последнее
известное, честно говоря, откуда оно взято.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..conditions import from_json as condition_from_json
from ..conditions import to_json as condition_to_json
from ..domain import Course, CourseKind
from .registration import Audience, CourseOffering

TERM = re.compile(r"^(Fall|Spring|Summer)\s+(\d{4})$")
# Порядок внутри года: весна, лето, осень.
SEASON_ORDER = {"Spring": 0, "Summer": 1, "Fall": 2}
# Осенние курсы читаются в нечётных семестрах плана, весенние — в чётных.
# Лето в сквозную нумерацию 1..8 не попадает вовсе.
SEASON_SEMESTERS = {"Fall": (1, 3, 5, 7), "Spring": (2, 4, 6, 8), "Summer": ()}


def term_key(term: str) -> tuple[int, int]:
    """Ключ сортировки семестров: Spring 2025 < Summer 2025 < Fall 2025."""
    match = TERM.match(term.strip())
    if not match:
        return (0, 0)
    return (int(match.group(2)), SEASON_ORDER[match.group(1)])


def season(term: str) -> str | None:
    """Время года семестра."""
    match = TERM.match(term.strip())
    return match.group(1) if match else None


@dataclass
class CatalogEntry:
    """Курс каталога: всё, что о нём сказали документы всех семестров."""

    code: str
    title: str = ""
    school: str = ""
    department: str = ""
    credits_ects: int | None = None
    # Семестр -> условие. Пререквизиты меняются между семестрами, и держать
    # их одним полем значило бы выдать прошлогоднее условие за сегодняшнее.
    prerequisites: dict[str, object] = field(default_factory=dict)
    corequisites: dict[str, object] = field(default_factory=dict)
    antirequisites: dict[str, object] = field(default_factory=dict)
    priorities: dict[str, list[list[Audience]]] = field(default_factory=dict)
    instructor_permission: bool = False
    # Семестры, в которых курс встретился. Отдельно от условий: курс может
    # читаться и без единого пререквизита, и потерять его было бы обидно —
    # именно по этому полю видно, в каком семестре курс вообще бывает.
    seen_terms: set[str] = field(default_factory=set)

    @property
    def terms(self) -> tuple[str, ...]:
        """Семестры, в которых курс читался, от старых к новым."""
        seen = set(self.prerequisites) | set(self.priorities) | self.seen_terms
        return tuple(sorted(seen, key=term_key))

    @property
    def seasons(self) -> frozenset[str]:
        return frozenset(s for s in map(season, self.terms) if s)

    @property
    def semesters_offered(self) -> tuple[int, ...]:
        """Семестры плана, в которых курс реально читают.

        Пусто — значит неизвестно: курс либо только летний, либо в разобранных
        документах не встретился. Пустое значение слой ограничений трактует
        как "ограничения нет", и это честнее запрета.
        """
        semesters: set[int] = set()
        for name in self.seasons:
            semesters.update(SEASON_SEMESTERS[name])
        return tuple(sorted(semesters))

    def latest(self, source: dict[str, object], term: str | None = None):
        """Последнее известное значение на этот семестр включительно."""
        known = [t for t in sorted(source, key=term_key) if term is None or term_key(t) <= term_key(term)]
        return source[known[-1]] if known else None

    def prerequisite(self, term: str | None = None):
        """Условие допуска: за этот семестр, иначе последнее известное."""
        return self.latest(self.prerequisites, term) or self.latest(self.prerequisites)

    def priority_for(
        self, year: int, school: str | None, program: str | None, term: str | None = None
    ) -> int | None:
        """Тир приоритета студента в этом семестре: 1 — самый высокий."""
        tiers = self.latest(self.priorities, term) or self.latest(self.priorities)
        if not tiers:
            return None
        for tier, audiences in enumerate(tiers, start=1):
            if any(a.matches(year, school, program) for a in audiences):
                return tier
        return None

    def course(self, kind: CourseKind = CourseKind.ELECTIVE, term: str | None = None) -> Course:
        """Доменный Course по записи каталога."""
        return Course(
            code=self.code,
            title=self.title,
            credits=self.credits_ects or 0,
            kind=kind,
            semesters_offered=self.semesters_offered,
            requirement=self.prerequisite(term),
        )


@dataclass
class Catalog:
    """Курсы университета по всем разобранным семестрам."""

    entries: dict[str, CatalogEntry] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, code: str) -> bool:
        return code in self.entries

    def get(self, code: str) -> CatalogEntry | None:
        return self.entries.get(code)

    @property
    def terms(self) -> tuple[str, ...]:
        return tuple(sorted({t for e in self.entries.values() for t in e.terms}, key=term_key))

    @property
    def titles(self) -> dict[str, str]:
        return {code: entry.title for code, entry in self.entries.items()}

    @property
    def schools(self) -> dict[str, str]:
        return {code: entry.school for code, entry in self.entries.items()}

    @property
    def credits(self) -> dict[str, int]:
        return {code: entry.credits_ects or 0 for code, entry in self.entries.items()}

    def in_term(self, term: str) -> dict[str, CatalogEntry]:
        """Курсы, читавшиеся ровно в этом семестре."""
        return {code: e for code, e in self.entries.items() if term in e.terms}

    def offered(self, term: str | None = None) -> set[str]:
        """Курсы, которые в этом семестре читают.

        Документа за нужный семестр может не быть — весенний выходит позже
        осеннего. Тогда остаётся сезон: курс, который читали три весны подряд,
        прочитают и этой весной. Это предположение, но оно ближе к правде,
        чем пустой список, из которого нечего рекомендовать.
        """
        if term is None:
            return set(self.entries)
        exact = set(self.in_term(term))
        if exact:
            return exact
        name = season(term)
        return {code for code, entry in self.entries.items() if name in entry.seasons}


def add(catalog: Catalog, offering: CourseOffering) -> None:
    """Добавить в каталог одну строку документа.

    Название и департамент берутся из самого позднего семестра: курсы
    переименовывают и передают между департаментами, и свежее вернее.
    """
    entry = catalog.entries.get(offering.code)
    if entry is None:
        entry = CatalogEntry(code=offering.code)
        catalog.entries[offering.code] = entry

    newest = not entry.terms or term_key(offering.term) >= term_key(entry.terms[-1])
    entry.seen_terms.add(offering.term)
    if newest:
        entry.title = offering.title or entry.title
        entry.school = offering.school or entry.school
        entry.department = offering.department or entry.department
        entry.credits_ects = offering.credits_ects or entry.credits_ects

    if offering.prerequisite is not None:
        entry.prerequisites[offering.term] = offering.prerequisite
    if offering.corequisite is not None:
        entry.corequisites[offering.term] = offering.corequisite
    if offering.antirequisite is not None:
        entry.antirequisites[offering.term] = offering.antirequisite
    if offering.priorities:
        entry.priorities[offering.term] = offering.priorities
    entry.instructor_permission = entry.instructor_permission or offering.instructor_permission


def build(offerings) -> Catalog:
    """Собрать каталог из разобранных строк документов."""
    catalog = Catalog()
    for offering in offerings:
        add(catalog, offering)
    return catalog


def from_pdfs(paths) -> Catalog:
    """Собрать каталог из документов Course Requirements."""
    from .registration import parse_pdf

    catalog = Catalog()
    for path in paths:
        for offering in parse_pdf(Path(path)):
            add(catalog, offering)
    return catalog


def _audience_to_json(audience: Audience) -> dict:
    return {
        "year": audience.year,
        "school": audience.school,
        "program": audience.program,
        "pending_graduation": audience.pending_graduation,
        "raw": audience.raw,
    }


def to_json(catalog: Catalog) -> list[dict]:
    """Каталог в JSON-совместимую структуру."""
    return [
        {
            "code": entry.code,
            "title": entry.title,
            "school": entry.school,
            "department": entry.department,
            "credits_ects": entry.credits_ects,
            "terms": list(entry.terms),
            "prerequisites": {
                term: condition_to_json(node) for term, node in entry.prerequisites.items()
            },
            "corequisites": {
                term: condition_to_json(node) for term, node in entry.corequisites.items()
            },
            "antirequisites": {
                term: condition_to_json(node) for term, node in entry.antirequisites.items()
            },
            "priorities": {
                term: [[_audience_to_json(a) for a in tier] for tier in tiers]
                for term, tiers in entry.priorities.items()
            },
            "instructor_permission": entry.instructor_permission,
        }
        for entry in sorted(catalog.entries.values(), key=lambda e: e.code)
    ]


def from_json(payload: list[dict]) -> Catalog:
    """Каталог обратно из JSON."""
    catalog = Catalog()
    for item in payload:
        catalog.entries[item["code"]] = CatalogEntry(
            code=item["code"],
            title=item.get("title", ""),
            school=item.get("school", ""),
            department=item.get("department", ""),
            credits_ects=item.get("credits_ects"),
            prerequisites={
                term: condition_from_json(node)
                for term, node in (item.get("prerequisites") or {}).items()
            },
            corequisites={
                term: condition_from_json(node)
                for term, node in (item.get("corequisites") or {}).items()
            },
            antirequisites={
                term: condition_from_json(node)
                for term, node in (item.get("antirequisites") or {}).items()
            },
            priorities={
                term: [[Audience(**a) for a in tier] for tier in tiers]
                for term, tiers in (item.get("priorities") or {}).items()
            },
            instructor_permission=item.get("instructor_permission", False),
            seen_terms=set(item.get("terms") or []),
        )
    return catalog


def save(catalog: Catalog, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_json(catalog), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load(path: Path) -> Catalog:
    """Прочитать каталог курсов с диска."""
    return from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def default_path() -> Path:
    from ..config import DATA_PROCESSED

    return DATA_PROCESSED / "catalog.json"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Собрать каталог курсов из документов Registrar")
    parser.add_argument("pdf", type=Path, nargs="+")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args()

    catalog = from_pdfs(args.pdf)
    seasons = {name: 0 for name in SEASON_ORDER}
    for entry in catalog.entries.values():
        for name in entry.seasons:
            seasons[name] += 1
    with_prereq = sum(1 for e in catalog.entries.values() if e.prerequisites)

    print(f"семестров: {len(catalog.terms)} ({', '.join(catalog.terms)})")
    print(f"курсов: {len(catalog)}, с пререквизитами: {with_prereq}")
    print("  " + ", ".join(f"{name.lower()}: {count}" for name, count in seasons.items()))

    output = args.output or default_path()
    save(catalog, output)
    print(f"-> {output}")


if __name__ == "__main__":
    main()
