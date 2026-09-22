"""Разбор расписания семестра со счётчиками регистрации.

Registrar выкладывает PDF со всеми секциями семестра, и в нём есть две
колонки, которых нет больше нигде: Enr — сколько человек записалось, Cap —
сколько мест. Это и есть целевая переменная для модели доступности: по ней
видно, какие курсы разбирают полностью, а какие стоят полупустыми.

Два наблюдения, которые задают форму модели:

* заполнено ровно или сверх нормы примерно половина секций, так что
  конкуренция реальна и измерима;
* почти четверть секций набирает БОЛЬШЕ мест, чем Cap. Переливы через капы
  массовые, поэтому "мест нет" нельзя читать как "не попасть" — это вопрос
  вероятности, а не запрета.

Файл — снимок на момент выгрузки. Несколько снимков одного семестра дают
динамику: сколько мест ушло между датами.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

TERM = re.compile(r"(Fall|Spring|Summer)\s+(\d{4})")
TAKEN_AT = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
SECTION_LABEL = re.compile(r"^(\d+)([A-Za-z]+)$")
ROOM = re.compile(r"^(.*?)\s*-\s*cap:(\d+)$")
TIME_RANGE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)")
DAY_CODES = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}
ONLINE = re.compile(r"online|distant", re.IGNORECASE)


@dataclass(frozen=True)
class Meeting:
    """Одна встреча секции: дни недели и время."""

    days: tuple[str, ...] = ()
    start: time | None = None
    end: time | None = None
    online: bool = False

    def overlaps(self, other: Meeting) -> bool:
        """Пересекаются ли встречи по времени хотя бы в один день."""
        if self.online or other.online:
            return False
        if not (set(self.days) & set(other.days)):
            return False
        if None in (self.start, self.end, other.start, other.end):
            return False
        return self.start < other.end and other.start < self.end


@dataclass
class Section:
    """Секция курса в конкретном семестре."""

    term: str
    code: str
    section: str
    title: str = ""
    school: str = ""
    level: str = ""
    credits_us: float | None = None
    credits_ects: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    meetings: list[Meeting] = field(default_factory=list)
    enrolled: int | None = None
    capacity: int | None = None
    faculty: tuple[str, ...] = ()
    room: str | None = None
    room_capacity: int | None = None
    taken_at: datetime | None = None

    @property
    def number(self) -> int | None:
        match = SECTION_LABEL.match(self.section)
        return int(match.group(1)) if match else None

    @property
    def kind(self) -> str:
        """Тип компонента: L — лекция, Lb — лаборатория, R — рецитация, S — семинар."""
        match = SECTION_LABEL.match(self.section)
        return match.group(2) if match else self.section

    @property
    def seats_left(self) -> int | None:
        if self.enrolled is None or self.capacity is None:
            return None
        return self.capacity - self.enrolled

    @property
    def fill_rate(self) -> float | None:
        if not self.capacity:
            return None
        return (self.enrolled or 0) / self.capacity

    @property
    def is_full(self) -> bool:
        return bool(self.capacity) and (self.enrolled or 0) >= self.capacity

    @property
    def is_over_capacity(self) -> bool:
        """Записано больше, чем мест: переливы через кап случаются массово."""
        return bool(self.capacity) and (self.enrolled or 0) > self.capacity

    def conflicts_with(self, other: Section) -> bool:
        """Пересекаются ли секции по расписанию."""
        return any(a.overlaps(b) for a in self.meetings for b in other.meetings)


@dataclass
class Snapshot:
    """Расписание семестра на момент выгрузки."""

    term: str
    taken_at: datetime | None
    sections: list[Section] = field(default_factory=list)

    @property
    def is_pre_registration(self) -> bool:
        """Снимок сделан до открытия регистрации: мест много, записей нет.

        Такие выгрузки полезны как базовая линия по вместимости, но спроса
        в них нет, и считать по ним заполняемость бессмысленно.
        """
        return bool(self.sections) and all((s.enrolled or 0) == 0 for s in self.sections)

    def filter_level(self, level: str = "UG") -> Snapshot:
        """Оставить только один уровень обучения.

        В части выгрузок вместе с бакалавриатом лежат магистратура, PhD и
        подготовительная программа — для рекомендаций бакалаврам они лишние.
        """
        return Snapshot(
            term=self.term,
            taken_at=self.taken_at,
            sections=[s for s in self.sections if s.level == level],
        )

    def by_course(self) -> dict[str, list[Section]]:
        courses: dict[str, list[Section]] = {}
        for section in self.sections:
            courses.setdefault(section.code, []).append(section)
        return courses

    def demand(self, kinds: tuple[str, ...] = ("L",)) -> dict[str, CourseDemand]:
        """Спрос по курсам.

        Считаем только по указанным типам компонентов: студент одной секции
        числится и в лекции, и в своей лаборатории, и в рецитации, поэтому
        суммировать всё подряд означало бы посчитать его несколько раз.
        """
        demand: dict[str, CourseDemand] = {}
        for code, sections in self.by_course().items():
            chosen = [s for s in sections if s.kind in kinds] or sections
            enrolled = sum(s.enrolled or 0 for s in chosen)
            capacity = sum(s.capacity or 0 for s in chosen)
            demand[code] = CourseDemand(
                code=code,
                title=chosen[0].title,
                term=self.term,
                sections=len(chosen),
                enrolled=enrolled,
                capacity=capacity,
            )
        return demand


@dataclass(frozen=True)
class CourseDemand:
    """Сводка спроса на курс за семестр."""

    code: str
    title: str
    term: str
    sections: int
    enrolled: int
    capacity: int

    @property
    def fill_rate(self) -> float | None:
        return self.enrolled / self.capacity if self.capacity else None

    @property
    def seats_left(self) -> int:
        return self.capacity - self.enrolled

    @property
    def is_full(self) -> bool:
        return bool(self.capacity) and self.enrolled >= self.capacity


@dataclass(frozen=True)
class CourseHistory:
    """Как курс заполнялся в прошлые семестры."""

    code: str
    title: str
    observations: tuple[tuple[str, float], ...] = ()  # (семестр, заполняемость)

    @property
    def terms(self) -> int:
        return len(self.observations)

    @property
    def last_fill(self) -> float | None:
        """Заполняемость в последний известный семестр."""
        return self.observations[-1][1] if self.observations else None

    @property
    def mean_fill(self) -> float | None:
        if not self.observations:
            return None
        return sum(rate for _, rate in self.observations) / len(self.observations)

    @property
    def ever_full(self) -> bool:
        return any(rate >= 1.0 for _, rate in self.observations)


def history(snapshots: list[Snapshot], kinds: tuple[str, ...] = ("L",)) -> dict[str, CourseHistory]:
    """Свести снимки в историю заполняемости по курсам.

    Снимки до открытия регистрации пропускаются: в них нули, и принять их за
    "никто не записался" значило бы занизить спрос. Если семестр представлен
    несколькими снимками, берётся самый поздний.
    """
    latest: dict[str, Snapshot] = {}
    for snapshot in snapshots:
        if snapshot.is_pre_registration or not snapshot.sections:
            continue
        current = latest.get(snapshot.term)
        if current is None or (
            snapshot.taken_at and current.taken_at and snapshot.taken_at > current.taken_at
        ):
            latest[snapshot.term] = snapshot

    collected: dict[str, list[tuple[str, float, str]]] = {}
    # Снимки без отметки времени ставим в начало — порядок семестров важнее.
    ordered = sorted(latest.values(), key=lambda s: (s.taken_at is not None, s.taken_at))
    for snapshot in ordered:
        for code, demand in snapshot.demand(kinds).items():
            if demand.fill_rate is not None:
                collected.setdefault(code, []).append((snapshot.term, demand.fill_rate, demand.title))

    return {
        code: CourseHistory(
            code=code,
            title=items[-1][2],
            observations=tuple((term, rate) for term, rate, _ in items),
        )
        for code, items in collected.items()
    }


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def parse_days(cell: str) -> tuple[str, ...]:
    """Дни недели: "M W F" -> ("M","W","F"). Повторы схлопываются."""
    seen: list[str] = []
    for token in normalize(cell).split():
        if token in DAY_CODES and token not in seen:
            seen.append(token)
    return tuple(seen)


def parse_time_range(cell: str) -> tuple[time | None, time | None]:
    match = TIME_RANGE.search(normalize(cell))
    if not match:
        return None, None

    def to_time(value: str) -> time | None:
        try:
            # В расписании указано местное время кампуса без пояса — подставлять
            # его было бы выдумкой, поэтому оставляем naive.
            return datetime.strptime(value.replace(" ", ""), "%I:%M%p").time()  # noqa: DTZ007
        except ValueError:
            return None

    return to_time(match.group(1)), to_time(match.group(2))


def parse_meetings(days_cell: str, time_cell: str) -> list[Meeting]:
    """Встречи секции. В одной ячейке может оказаться несколько интервалов."""
    text = normalize(time_cell)
    if not text:
        return []
    if ONLINE.search(text) and not TIME_RANGE.search(text):
        return [Meeting(online=True)]

    days = parse_days(days_cell)
    meetings = []
    for match in TIME_RANGE.finditer(text):
        start, end = parse_time_range(match.group(0))
        meetings.append(Meeting(days=days, start=start, end=end))
    return meetings


def parse_room(cell: str) -> tuple[str | None, int | None]:
    """"8.310 - cap:30" -> ("8.310", 30)."""
    text = normalize(cell)
    if not text:
        return None, None
    match = ROOM.match(text)
    if not match:
        return text, None
    return (match.group(1) or None), int(match.group(2))


def parse_faculty(cell: str) -> tuple[str, ...]:
    text = normalize(cell)
    if not text or text.upper() == "TBA TBA":
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


def parse_date(cell: str) -> date | None:
    text = normalize(cell)
    try:
        return datetime.strptime(text, "%d-%b-%y").date()  # noqa: DTZ007
    except ValueError:
        return None


def _int(cell: str) -> int | None:
    text = normalize(cell)
    return int(text) if text.isdigit() else None


def _float(cell: str) -> float | None:
    try:
        return float(normalize(cell))
    except ValueError:
        return None


def is_continuation(cells: list[str]) -> bool:
    """Строка с дополнительным временем той же секции: заполнены только дни и время."""
    if cells[2] or cells[0]:
        return False
    return bool(cells[9] or cells[10])


def parse_row(cells: list[str], term: str, taken_at: datetime | None) -> Section | None:
    code = normalize(cells[2])
    if not code:
        return None
    room, room_capacity = parse_room(cells[14] if len(cells) > 14 else "")
    return Section(
        term=term,
        code=code,
        section=normalize(cells[3]),
        title=normalize(cells[4]),
        school=normalize(cells[0]),
        level=normalize(cells[1]),
        credits_us=_float(cells[5]),
        credits_ects=_int(cells[6]),
        start_date=parse_date(cells[7]),
        end_date=parse_date(cells[8]),
        meetings=parse_meetings(cells[9], cells[10]),
        enrolled=_int(cells[11]),
        capacity=_int(cells[12]),
        faculty=parse_faculty(cells[13] if len(cells) > 13 else ""),
        room=room,
        room_capacity=room_capacity,
        taken_at=taken_at,
    )


def merge_sections(sections: list[Section]) -> list[Section]:
    """Склеить строки одной секции.

    Секцию печатают несколькими строками, когда у неё разные встречи:
    онлайн-лекция в понедельник и очная в пятницу — это одна и та же запись
    с одним Enr, и считать её дважды нельзя.
    """
    merged: dict[tuple[str, str], Section] = {}
    for section in sections:
        key = (section.code, section.section)
        existing = merged.get(key)
        if existing is None:
            merged[key] = section
            continue
        for meeting in section.meetings:
            if meeting not in existing.meetings:
                existing.meetings.append(meeting)
        # Enr изредка расходится между строками — берём больший.
        if (section.enrolled or 0) > (existing.enrolled or 0):
            existing.enrolled = section.enrolled
        if existing.room is None:
            existing.room, existing.room_capacity = section.room, section.room_capacity
    return list(merged.values())


def parse_pdf(path: Path) -> Snapshot:
    """Разобрать расписание семестра."""
    import pdfplumber

    sections: list[Section] = []
    term, taken_at = "", None
    with pdfplumber.open(path) as pdf:
        header = pdf.pages[0].extract_text() or ""
        match = TERM.search(header)
        term = f"{match.group(1)} {match.group(2)}" if match else path.stem
        stamp = TAKEN_AT.search(header)
        if stamp:
            taken_at = datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007

        for page in pdf.pages:
            table = page.extract_table()
            if not table:
                continue
            for row in table:
                if not row:
                    continue
                cells = [normalize(c) for c in row]
                cells += [""] * (15 - len(cells))
                if cells[0] == "School":
                    continue
                if is_continuation(cells) and sections:
                    sections[-1].meetings.extend(parse_meetings(cells[9], cells[10]))
                    continue
                section = parse_row(cells, term, taken_at)
                if section is not None:
                    sections.append(section)

    return Snapshot(term=term, taken_at=taken_at, sections=merge_sections(sections))


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Разобрать расписание семестра")
    parser.add_argument("pdf", type=Path, nargs="+")
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()

    payload = []
    for path in args.pdf:
        snapshot = parse_pdf(path)
        full = sum(1 for s in snapshot.sections if s.is_full)
        over = sum(1 for s in snapshot.sections if s.is_over_capacity)
        stamp = snapshot.taken_at.date().isoformat() if snapshot.taken_at else "?"
        print(
            f"{snapshot.term:12s} {stamp}  секций {len(snapshot.sections):4d}  "
            f"заполнено {full:4d} ({full / max(len(snapshot.sections), 1):.0%})  "
            f"сверх капа {over:3d}"
        )
        payload.append(
            {
                "term": snapshot.term,
                "taken_at": snapshot.taken_at.isoformat() if snapshot.taken_at else None,
                "sections": [
                    {
                        "code": s.code,
                        "section": s.section,
                        "title": s.title,
                        "school": s.school,
                        "enrolled": s.enrolled,
                        "capacity": s.capacity,
                        "credits_ects": s.credits_ects,
                        "meetings": [
                            {
                                "days": list(m.days),
                                "start": m.start.isoformat() if m.start else None,
                                "end": m.end.isoformat() if m.end else None,
                                "online": m.online,
                            }
                            for m in s.meetings
                        ],
                        "faculty": list(s.faculty),
                        "room": s.room,
                    }
                    for s in snapshot.sections
                ],
            }
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {args.output}")


if __name__ == "__main__":
    main()
