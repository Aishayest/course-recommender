"""Списки элективов: у каждой специальности свой.

Handbook отводит под элективы отдельные страницы — по одной на специальность,
и это не формальность: технический электив CS и технический электив робототехники
пересекаются лишь частично. Для CS засчитывается MATH 322 и ELCE 202, для ROBT —
нет; у ROBT список закрытый из шести ROBT-курсов. Поэтому ключ здесь всегда
"год поступления + специальность + тип электива", а не один общий список.

Формулируются списки тремя способами, и все три встречаются одновременно:

* правилом — "any non-required course at 200-level or above offered by the CS
  department": множество задано предметом и уровнем, перечислить его без
  каталога нельзя;
* явным перечнем с кодами — таблица "MATH 322 Mathematical Statistics";
* перечнем одних названий, без кодов — так оформлены элективы инженерных
  специальностей (ECE, MAE, CEE, CHME) и PETE. Код восстанавливается только
  сопоставлением с каталогом.

Поэтому ElectiveGroup хранит всё, что сказал handbook, а превращение в набор
кодов вынесено в resolve(): без каталога правило нераскрываемо, и делать вид,
что список известен, нельзя.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .canva import Page
from .handbook import COURSE_CODE, CourseRef, normalize

# Типы элективов. Совпадают с тем, как позиции названы в учебном плане:
# "Technical Elective 2", "Natural Science Elective", "ELCE Elective 3".
TECHNICAL = "technical"
NATURAL_SCIENCE = "natural science"
MAJOR = "major"
GENERAL = "general"
SOCIAL_SCIENCE = "social science"
HUMANITIES = "humanities"
# Позиция общеуниверситетского ядра: язык, этика, письмо.
CORE = "core"

# Порядок важен: "Natural Science" проверяется раньше "Science", иначе
# естественнонаучный электив попал бы в социальные науки.
KIND_HINTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"natural\s+science", re.IGNORECASE), NATURAL_SCIENCE),
    (re.compile(r"technical", re.IGNORECASE), TECHNICAL),
    (re.compile(r"social\s+science", re.IGNORECASE), SOCIAL_SCIENCE),
    (re.compile(r"humanit", re.IGNORECASE), HUMANITIES),
    (re.compile(r"general|open", re.IGNORECASE), GENERAL),
    (re.compile(r"major", re.IGNORECASE), MAJOR),
)

ELECTIVE = re.compile(r"elective", re.IGNORECASE)
# "Geology TECHNICAL ELECTIVES", "PHYSICS ELECTIVE COURSES",
# "COMPUTER SCIENCE TECHNICAL AND NATURAL SCIENCE ELECTIVES"
HEADING_TAIL = re.compile(
    r"\s*(technical\s+and\s+natural\s+science|technical|natural\s+science)?"
    r"\s*elective[s]?(\s+courses)?\s*$",
    re.IGNORECASE,
)
# Уровень: "at 200-level or above", "300– or 400-level", "200+ coded".
# Берётся минимальный из названных: "300 or 400-level" открывает и третий курс.
LEVEL = re.compile(r"\b(\d)00\b(?=[^.]{0,30}?(?:level|\+))", re.IGNORECASE)
NON_REQUIRED = re.compile(
    r"non-required|not\s+required|not\s+included\s+(?:in\s+)?(?:the\s+)?degree", re.IGNORECASE
)
ADVISOR = re.compile(r"consent|approval\s+of\s+the\s+advisor", re.IGNORECASE)
# "ROBT-coded courses", "MATH courses", "Any SoE or MATH course"
SUBJECT_TOKEN = re.compile(
    r"\b([A-Z]{3,5})\b(?=\s*-?\s*coded|\s+courses?\b|\s+electives?\b)"
)
# "Any HST courses (except HST 100)" — правило вместе с изъятием из него.
ANY_SUBJECT = re.compile(r"\bany\s+[A-Za-z]{2,20}\b[^.]{0,40}?\bcourses?\b", re.IGNORECASE)
EXCEPT = re.compile(r"\bexcept\b(.*)$", re.IGNORECASE)
MINOR = re.compile(r"\bminor\b", re.IGNORECASE)
# Тип электива объявляется в начале фразы: "Technical Electives are ...".
# Слово из середины брать нельзя: примечание ECE упоминает технические
# стажировки, но описывает при этом профильные элективы специальности.
KIND_PREFIX = re.compile(r"^(.{0,40}?)\belectives?\b", re.IGNORECASE | re.DOTALL)
OFFERED_BY = re.compile(r"offered\s+by\s+(.+?)(?=\s+at\s+\d00|\s+that\b|[.;:]|$)", re.IGNORECASE)
# Явный перечень заменяет правило: "ROBT-coded courses in the list below".
DEFERS_TO_LIST = re.compile(r"in\s+the\s+list\s+below", re.IGNORECASE)
SENTENCE = re.compile(r"(?<=[.;])\s+")
LEADING_MARKER = re.compile(r"^[*•\s]+")
TOTAL_ROW = re.compile(r"^total\b", re.IGNORECASE)
SERIAL = re.compile(r"^\d{1,2}$")
TABLE_HEADER = re.compile(r"^(no|#|course\s+title|title|credits?|ects)$", re.IGNORECASE)
COUNT_PHRASE = re.compile(r"choose\s+(?:at\s+least\s+)?(\d+)", re.IGNORECASE)

# Название департамента в тексте правила -> префикс курса в каталоге.
SUBJECT_OF_DEPARTMENT = {
    "physics": "PHYS",
    "chemistry": "CHEM",
    "biology": "BIOL",
    "biological sciences": "BIOL",
    "geology": "GEOL",
    "geosciences": "GEOL",
    "mathematics": "MATH",
    "math": "MATH",
    "cs": "CSCI",
    "computer science": "CSCI",
    "robotics": "ROBT",
    "economics": "ECON",
    "sociology": "SOC",
    "anthropology": "ANT",
    "history": "HST",
    "philosophy": "PHIL",
    "psir": "PLS",
    "political science": "PLS",
}
# Прописными в handbook набраны не только коды предметов. Эти слова кодами
# курсов не являются, и без списка-исключения "EAP course is required"
# превратилось бы в предмет EAP.
STOP_SUBJECTS = frozenset(
    {"EAP", "ECTS", "GPA", "CGPA", "IELTS", "UG", "AND", "OR", "ANY", "ALL", "NU", "BSC", "BS"}
)
# Названия предметов словами: "Four 300-level Economics electives".
SUBJECT_WORDS = re.compile(
    r"((?:[A-Za-z0-9][A-Za-z0-9–-]{1,19}[\s,]+){0,4})(?:courses?|electives?)\b", re.IGNORECASE
)
ANY_COURSES = re.compile(r"\bany\b[^.]{0,40}?\b(?:courses?|electives?)\b", re.IGNORECASE)
# Категория, записанная одними кодами предметов: "ANT ECON PLS SOC".
SUBJECT_LIST = re.compile(r"^(?:[A-Z]{2,5}[\s,/]+)+[A-Z]{2,5}$")

# Школы в правилах записаны сокращением, и состав школы известен не из handbook,
# а из документа регистрации: там у каждого курса проставлена школа.
SCHOOL_NAMES = {"soe", "seds", "scai", "ssh", "som", "gsb", "smg"}


@dataclass(frozen=True)
class ElectiveRule:
    """Правило, задающее множество элективов без перечисления.

    "any non-required course at 200-level or above offered by the CS department"
    разворачивается в subjects=("CSCI",), min_level=200, exclude_required=True.
    Раскрыть такое правило можно только имея каталог курсов.
    """

    subjects: tuple[str, ...] = ()
    schools: tuple[str, ...] = ()
    min_level: int | None = None
    exclude_required: bool = False
    # "with the consent of the advisor" — не право студента, а разрешение,
    # которого может и не быть. Такие курсы не подставляются молча.
    advisor_consent: bool = False
    # Изъятия из правила: "Any HST courses (except HST 100)".
    exclude_codes: frozenset[str] = frozenset()
    raw: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.subjects and not self.schools

    def matches(self, code: str, required: frozenset[str] = frozenset(), school: str | None = None) -> bool:
        """Подходит ли курс под правило."""
        match = COURSE_CODE.match(code)
        if not match:
            return False
        subject, number = match.group(1), int(match.group(2)[:3])
        if code in self.exclude_codes:
            return False
        if self.exclude_required and code in required:
            return False
        if self.min_level is not None and number < self.min_level:
            return False
        if subject in self.subjects:
            return True
        return bool(self.schools and school and school.upper() in self.schools)


@dataclass
class ElectiveGroup:
    """Всё, что handbook сказал про один тип элективов одной специальности."""

    admission_year: int
    program: str
    kind: str
    # Перечисленные с кодом — прямое указание handbook, каталог для них не нужен.
    courses: list[CourseRef] = field(default_factory=list)
    # Перечисленные одним названием: код восстанавливается только по каталогу.
    titles: list[str] = field(default_factory=list)
    # Области специализации: ECE требует выбирать из основной и смежной области.
    areas: dict[str, list[str]] = field(default_factory=dict)
    rules: list[ElectiveRule] = field(default_factory=list)
    # Сколько курсов этого типа нужно выбрать, если handbook это говорит.
    count: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def listed_codes(self) -> set[str]:
        """Коды, названные handbook напрямую."""
        return {ref.code for ref in self.courses if ref.code}

    def resolve(
        self,
        catalog: Mapping[str, str] | Iterable[str] = (),
        required: frozenset[str] = frozenset(),
        schools: Mapping[str, str] | None = None,
        include_advisor: bool = False,
    ) -> set[str]:
        """Развернуть группу в набор кодов курсов.

        Явно перечисленное входит всегда: это утверждение handbook, и оно не
        перестаёт быть верным оттого, что курс не читают в этом семестре.
        Правила же разворачиваются только по каталогу — без него множество
        "любой курс CS 200+" неизвестно, и придумывать его нельзя.
        """
        titles = dict(catalog) if isinstance(catalog, Mapping) else {code: "" for code in catalog}
        codes = self.listed_codes | match_titles(self.titles, titles)
        for rule in self.rules:
            if rule.advisor_consent and not include_advisor:
                continue
            school_of = schools or {}
            codes |= {
                code
                for code in titles
                if rule.matches(code, required, school_of.get(code))
            }
        return codes


def hinted_kind(text: str) -> str | None:
    """Тип электива, названный в тексте прямо. None — не назван."""
    for pattern, kind in KIND_HINTS:
        if pattern.search(text or ""):
            return kind
    return None


def elective_kind(text: str) -> str | None:
    """Тип электива по заголовку или тексту правила."""
    if not ELECTIVE.search(text or ""):
        return None
    # "PHYSICS ELECTIVE COURSES", "ELCE Elective 3" — профильные курсы
    # специальности, отдельного слова для них handbook не использует.
    return hinted_kind(text) or MAJOR


def leading_kind(text: str) -> str | None:
    """Тип электива, объявленный в начале фразы.

    "Technical Electives are ROBT-coded courses" -> technical, а вот
    "Students should choose at least 5 elective courses ..." типа не называет:
    такая фраза описывает элективы той страницы, на которой написана.
    """
    match = KIND_PREFIX.match(normalize(text))
    return hinted_kind(match.group(1)) if match else None


def slot_kind(name: str) -> str | None:
    """Тип электива по названию позиции плана.

    "Technical Elective 2" -> technical, "ELCE Elective 3" -> major:
    у инженерных специальностей профильный электив назван кодом департамента,
    и страница handbook для него озаглавлена "... ELECTIVE COURSES".
    """
    return elective_kind(name or "")


def program_of_heading(heading: str) -> str:
    """Название специальности из заголовка страницы элективов.

    "Geology TECHNICAL ELECTIVES" -> "GEOLOGY",
    "Robotics Engineering Natural Science ELECTIVEs" -> "ROBOTICS ENGINEERING".
    """
    text = normalize(heading)
    text = re.sub(r"^list\s+of\s+", "", text, flags=re.IGNORECASE)
    return HEADING_TAIL.sub("", text).strip(" -–:").upper()


def parse_subjects(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Предметы и школы, названные в правиле."""
    subjects: list[str] = []
    schools: list[str] = []

    for token in SUBJECT_TOKEN.findall(text):
        if token.lower() in SCHOOL_NAMES:
            schools.append(token.upper())
        elif token in STOP_SUBJECTS:
            continue
        else:
            # "PSIR electives" — специальность названа аббревиатурой,
            # а курсы у неё с кодом PLS.
            subjects.append(SUBJECT_OF_DEPARTMENT.get(token.lower(), token))

    for word in re.findall(r"\b(SoE|SEDS|SCAI|SSH|SoM|GSB|SMG)\b", text):
        if word.upper() not in schools:
            schools.append(word.upper())

    for fragment in SUBJECT_WORDS.findall(text):
        for word in re.split(r"[\s,]+", fragment):
            subject = SUBJECT_OF_DEPARTMENT.get(word.strip().lower())
            if subject and subject not in subjects:
                subjects.append(subject)

    match = OFFERED_BY.search(text)
    if match:
        fragment = re.sub(r"\b(the|department|departments)\b", " ", match.group(1), flags=re.IGNORECASE)
        for part in re.split(r",|\band\b|\bor\b", fragment):
            subject = SUBJECT_OF_DEPARTMENT.get(normalize(part).lower())
            if subject and subject not in subjects:
                subjects.append(subject)

    return tuple(dict.fromkeys(subjects)), tuple(dict.fromkeys(schools))


def parse_min_level(text: str) -> int | None:
    """Минимальный уровень курса из перечисления уровней.

    "Any Math 300– or 400-level courses" открывает и третий курс, поэтому из
    названных уровней берётся наименьший, а не первый попавшийся.
    """
    levels = [int(digit) * 100 for digit in LEVEL.findall(text)]
    return min(levels) if levels else None


def parse_exclusions(text: str) -> frozenset[str]:
    """Коды, изъятые из правила: "Any HST courses (except HST 100)"."""
    match = EXCEPT.search(text)
    if not match:
        return frozenset()
    return frozenset(
        f"{code} {number}" for code, number in COURSE_CODE.findall(match.group(1))
    )


def parse_rule(text: str) -> ElectiveRule | None:
    """Разобрать одно предложение правила."""
    text = normalize(text)
    if not text or DEFERS_TO_LIST.search(text):
        return None

    subjects, schools = parse_subjects(text)
    if not subjects and not schools:
        return None

    return ElectiveRule(
        subjects=subjects,
        schools=schools,
        min_level=parse_min_level(text),
        exclude_required=bool(NON_REQUIRED.search(text)),
        advisor_consent=bool(ADVISOR.search(text)),
        exclude_codes=parse_exclusions(text),
        raw=text,
    )


def parse_subject_list(text: str) -> ElectiveRule | None:
    """Правило из голого перечня предметов.

    Под заголовком "Social Science electives" стоит строка "ANT ECON PLS SOC"
    и больше ничего: это и есть определение категории — любой курс этих
    предметов. Слова "courses" в ней нет, поэтому обычный разбор правила её
    не видит и принимает за название курса.
    """
    text = normalize(text)
    if not SUBJECT_LIST.match(text):
        return None
    subjects = tuple(
        token for token in re.split(r"[\s,/]+", text) if token and token not in STOP_SUBJECTS
    )
    # Один код — это скорее обрывок названия, чем перечень категорий.
    return ElectiveRule(subjects=subjects, raw=text) if len(subjects) > 1 else None


def parse_rules(text: str) -> list[ElectiveRule]:
    """Разобрать текст правила, в котором может быть несколько предложений.

    "Technical Electives are ROBT-coded courses in the list below. Any SoE or
    MATH courses with the consent of the advisor." — первое предложение
    отсылает к списку, второе задаёт правило с разрешением советника.
    """
    rules = []
    for sentence in SENTENCE.split(LEADING_MARKER.sub("", normalize(text))):
        rule = parse_rule(sentence)
        if rule is not None:
            rules.append(rule)
    return rules


def filled_rows(rows: list[list[str]]) -> list[list[str]]:
    """Строки, в которых есть хоть что-то: Canva оставляет пустые хвосты."""
    return [row for row in rows if any(clean_cell(cell) for cell in row)]


def is_prose(rows: list[list[str]]) -> bool:
    """Таблица из одной ячейки с текстом — это правило, а не перечень."""
    body = filled_rows(rows)
    if len(body) != 1 or len([c for c in body[0] if clean_cell(c)]) != 1:
        return False
    cell = normalize(next(c for c in body[0] if clean_cell(c)))
    return len(cell) > 60 and " " in cell


def clean_cell(cell: str | None) -> str:
    return normalize(cell or "")


def parse_listing(rows: list[list[str]]) -> tuple[list[CourseRef], list[str], dict[str, list[str]]]:
    """Разобрать таблицу-перечень: курсы с кодами, названия без кодов, области.

    Формы: "No | Course Title | Credits" (Geology, ROBT), "Title (CODE) | Credits"
    (Physics), одна колонка (CS) и таблица по областям специализации, где
    заголовки колонок — области, а ячейки — названия курсов (ECE, MAE, CEE).
    """
    courses: list[CourseRef] = []
    titles: list[str] = []
    areas: dict[str, list[str]] = {}

    body = [row for row in rows if any(clean_cell(c) for c in row)]
    if not body:
        return courses, titles, areas

    header = [clean_cell(c) for c in body[0]]
    # Область указана заголовком колонки: ячейки под ней — названия курсов.
    is_areas = len(header) > 1 and all(
        cell and not COURSE_CODE.search(cell) and not TABLE_HEADER.match(cell) for cell in header
    )
    if is_areas:
        areas = {name: [] for name in header}
        for row in body[1:]:
            for column, cell in enumerate(row[: len(header)]):
                value = clean_cell(cell).lstrip("•").strip()
                if not value or TOTAL_ROW.match(value):
                    continue
                areas[header[column]].append(value)
                # У CEE курсы в области записаны с кодом, у MAE — одним
                # названием. Код, если он есть, надёжнее названия.
                match = COURSE_CODE.search(value)
                if match:
                    courses.append(
                        CourseRef(
                            code=f"{match.group(1)} {match.group(2)}",
                            title=normalize(value.replace(match.group(0), " ")),
                        )
                    )
                else:
                    titles.append(value)
        return courses, titles, areas

    for row in body:
        cells = [clean_cell(c) for c in row]
        if all(not cell or TABLE_HEADER.match(cell) or SERIAL.match(cell) for cell in cells):
            continue
        for cell in cells:
            if not cell or SERIAL.match(cell) or TOTAL_ROW.match(cell) or TABLE_HEADER.match(cell):
                continue
            if cell.isdigit():
                continue
            match = COURSE_CODE.search(cell)
            if match:
                code = f"{match.group(1)} {match.group(2)}"
                title = normalize(cell.replace(match.group(0), " ").replace("()", " "))
                courses.append(CourseRef(code=code, title=title.strip(" -–()")))
            else:
                titles.append(cell.lstrip("•").strip())
    return courses, titles, areas


def _is_heading(text: str) -> bool:
    """Короткая строка-заголовок, а не абзац примечания."""
    text = normalize(text)
    return 0 < len(text) <= 70 and not text.endswith(".")


def parse_page(page: Page, admission_year: int) -> list[ElectiveGroup]:
    """Разобрать одну страницу элективов.

    Секции на странице разделяются заголовками, и заголовок решает судьбу
    таблицы под ним. Это важнее, чем кажется: на странице элективов CS ниже
    идёт "Transfer requirements" со списком CSCI-курсов, а у робототехники —
    "Minor in Robotics Engineering". Перепутать их с элективами значило бы
    предложить студенту курсы, которые требование не закрывают.
    """
    blocks = sorted(page.blocks, key=lambda b: (b.top, b.left))
    program: str | None = None
    page_kind: str | None = None
    section: str | None = None
    groups: dict[str, ElectiveGroup] = {}

    def group_for(kind: str) -> ElectiveGroup:
        return groups.setdefault(
            kind, ElectiveGroup(admission_year=admission_year, program=program or "", kind=kind)
        )

    def note(kind: str, text: str) -> None:
        group = group_for(kind)
        group.notes.append(text)
        count = COUNT_PHRASE.search(text)
        if count and group.count is None:
            group.count = int(count.group(1))

    for block in blocks:
        if block.kind == "text":
            text = normalize(block.text)
            kind = elective_kind(text)
            if program is None:
                # Заголовок страницы: он же называет специальность.
                if kind is not None and program_of_heading(text) and not MINOR.search(text):
                    program, page_kind, section = program_of_heading(text), kind, kind
            elif _is_heading(text):
                # Заголовок без слова "elective" закрывает секцию элективов.
                section = None if MINOR.search(text) else kind
            elif kind is not None and COUNT_PHRASE.search(text):
                note(section or page_kind or kind, text)
            continue

        if program is None or block.table is None:
            continue

        rows = block.table.rows
        body = filled_rows(rows)
        if len(body) == 1 and len([c for c in body[0] if clean_cell(c)]) == 1:
            subjects = parse_subject_list(next(c for c in body[0] if clean_cell(c)))
            if subjects is not None and section is not None:
                group = group_for(section)
                group.rules.append(subjects)
                group.notes.append(subjects.raw)
                continue

        if is_prose(rows):
            text = normalize(next(c for c in filled_rows(rows)[0] if clean_cell(c)))
            kind = leading_kind(text) or section or page_kind
            if kind is None:
                continue
            group = group_for(kind)
            rules = parse_rules(text)
            group.rules.extend(rules)
            # Правило и перечень бывают в одной ячейке: "Any LING courses"
            # и следом поимённо ANT 385, PLS 325. Одно другого не отменяет.
            excluded = frozenset().union(*(r.exclude_codes for r in rules)) if rules else frozenset()
            codes = [f"{s} {n}" for s, n in COURSE_CODE.findall(text)]
            if len(codes) > 1:
                group.courses.extend(
                    CourseRef(code=code, title="") for code in codes if code not in excluded
                )
            note(kind, text)
            continue

        if section is None:
            continue
        courses, titles, areas = parse_listing(rows)
        if not courses and not titles:
            continue
        group = group_for(section)
        group.courses.extend(courses)
        group.titles.extend(titles)
        for name, names in areas.items():
            group.areas.setdefault(name, []).extend(names)

    return list(groups.values())


def match_program(heading: str, programs: Iterable[str]) -> str | None:
    """Сопоставить заголовок страницы с названием специальности из планов.

    В плане специальность записана как "COMPUTER SCIENCE (CS)", а заголовок
    страницы элективов — "COMPUTER SCIENCE". Скобочное уточнение отбрасывается.
    """
    target = normalize(heading).upper()
    if not target:
        return None
    for name in programs:
        bare = re.sub(r"\([^)]*\)", " ", name)
        if normalize(bare).upper() == target:
            return name
    for name in programs:
        bare = normalize(re.sub(r"\([^)]*\)", " ", name)).upper()
        if bare.startswith(target) or target.startswith(bare):
            return name
    return None


def parse_electives(
    pages: list[Page], admission_year: int, programs: Iterable[str] = ()
) -> dict[tuple[str, str], ElectiveGroup]:
    """Собрать списки элективов всех специальностей одного выпуска handbook.

    Ключ — пара "специальность + тип электива": технический электив CS и
    технический электив робототехники это разные множества, и сливать их
    в один список нельзя.
    """
    names = list(programs)
    collected: dict[tuple[str, str], ElectiveGroup] = {}
    for page in pages:
        for group in parse_page(page, admission_year):
            # Заголовок, не совпавший ни с одной специальностью, — это
            # общеуниверситетская страница элективов. Пустое имя честнее
            # выдуманной специальности "SOCIAL SCIENCE, HUMANITIES AND GENERAL".
            program = match_program(group.program, names) or ""
            group.program = program
            key = (program, group.kind)
            existing = collected.get(key)
            if existing is None:
                collected[key] = group
                continue
            existing.courses.extend(group.courses)
            existing.titles.extend(group.titles)
            existing.rules.extend(group.rules)
            existing.notes.extend(group.notes)
            existing.count = existing.count or group.count
            for name, values in group.areas.items():
                existing.areas.setdefault(name, []).extend(values)
    return collected


def normalize_title(title: str) -> str:
    """Название курса для сравнения: без пунктуации, регистра и лишних пробелов."""
    text = normalize(title).lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_titles(titles: Iterable[str], catalog: Mapping[str, str]) -> set[str]:
    """Коды курсов по названиям из handbook.

    Совпадение только точное. Похожие названия ("Machine Learning with
    Applications" и "Statistical Methods and Machine Learning") — разные курсы,
    и угадывать здесь означало бы подсунуть студенту не тот курс.
    """
    index: dict[str, str] = {}
    for code, title in catalog.items():
        key = normalize_title(title)
        if key:
            index.setdefault(key, code)
    return {index[key] for key in map(normalize_title, titles) if key in index}


# В профильной секции общеуниверситетских элективов не бывает: "General
# Economics Electives" — это экономика вообще, а не свободный выбор.
MAJOR_SECTION_KINDS = frozenset({MAJOR, TECHNICAL, NATURAL_SCIENCE})


def kind_of_row(row) -> str:
    """Тип электива по строке таблицы требований."""
    kind = hinted_kind(f"{row.name} {row.explanation}")
    if row.section == "major":
        return kind if kind in MAJOR_SECTION_KINDS else MAJOR
    return kind or GENERAL


def groups_from_requirements(rows, admission_year: int) -> dict[tuple[str, str], ElectiveGroup]:
    """Списки элективов, заданные таблицей требований, а не отдельной страницей.

    Своей страницы элективов нет у большинства специальностей SSH и у
    математиков: там свобода выбора описана прямо в таблице требований —
    "Any Math 300- or 400-level courses", "Four 300-level Economics electives".
    Это то же самое множество, только записанное иначе, и оно тоже своё
    у каждой специальности.
    """
    collected: dict[tuple[str, str], ElectiveGroup] = {}
    for row in rows:
        if row.is_total:
            continue
        source = normalize(f"{row.name} {row.explanation}")
        # Строка про конкретный обязательный курс требованием выбора не является:
        # "Two KAZ courses" — это обязательный казахский, а не электив.
        if not (ELECTIVE.search(source) or ANY_COURSES.search(source)):
            continue

        kind = kind_of_row(row)
        group = collected.setdefault(
            (row.program, kind),
            ElectiveGroup(admission_year=admission_year, program=row.program, kind=kind),
        )
        rule = parse_rule(source)
        if rule is not None:
            group.rules.append(rule)
        # Перечень вариантов из строки: "Any two courses from MATH 407, 411, 440".
        for ref in row.courses:
            if ref.code:
                group.courses.append(ref)
        # Требований одного типа у специальности бывает несколько: у экономистов
        # четыре электива 300-го уровня и три 400-го. Множество курсов у них
        # общее, а вот брать нужно все семь.
        if row.count:
            group.count = (group.count or 0) + row.count
        group.notes.append(source)
    return collected


def merge(*sources: dict[tuple[str, str], ElectiveGroup]) -> dict[tuple[str, str], ElectiveGroup]:
    """Слить источники, не теряя ни одного: страница и таблица дополняют друг друга."""
    merged: dict[tuple[str, str], ElectiveGroup] = {}
    for source in sources:
        for key, group in source.items():
            existing = merged.get(key)
            if existing is None:
                merged[key] = group
                continue
            existing.courses.extend(group.courses)
            existing.titles.extend(group.titles)
            existing.rules.extend(group.rules)
            existing.notes.extend(group.notes)
            existing.count = existing.count or group.count
            for name, values in group.areas.items():
                existing.areas.setdefault(name, []).extend(values)
    return merged


def describe(group: ElectiveGroup) -> str:
    """Одна строка про то, чем задан список."""
    parts = []
    if group.listed_codes:
        parts.append(f"перечислено {len(group.listed_codes)}")
    if group.titles:
        parts.append(f"названий без кода {len(group.titles)}")
    if group.areas:
        parts.append(f"областей {len(group.areas)}")
    for rule in group.rules:
        target = "+".join(rule.subjects + rule.schools) or "?"
        level = f" {rule.min_level}+" if rule.min_level else ""
        note = " (с согласия советника)" if rule.advisor_consent else ""
        parts.append(f"правило: {target}{level}{note}")
    return "; ".join(parts) or "пусто"


def load_groups(admission_year: int) -> dict[tuple[str, str], ElectiveGroup]:
    """Списки элективов выпуска handbook из обоих источников."""
    from ..config import handbook_path
    from .canva import load
    from .handbook import parse_plans
    from .requirements import parse_requirements

    pages = load(handbook_path(admission_year))
    programs = {entry.program for entry in parse_plans(pages, admission_year)}
    return merge(
        parse_electives(pages, admission_year, programs),
        groups_from_requirements(parse_requirements(pages, admission_year), admission_year),
    )


def main() -> None:
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Показать списки элективов специальностей")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--program", help="часть названия, без учёта регистра")
    parser.add_argument("--catalog", type=Path, help="PDF Course Requirements — раскрыть правила")
    args = parser.parse_args()

    groups = load_groups(args.year)
    catalog: dict[str, str] = {}
    schools: dict[str, str] = {}
    if args.catalog:
        from .registration import parse_pdf

        offerings = parse_pdf(args.catalog)
        catalog = {offering.code: offering.title for offering in offerings}
        schools = {offering.code: offering.school for offering in offerings}

    from .assemble import load_programs

    programs = load_programs(args.year)

    for (program, kind), group in sorted(groups.items()):
        if args.program and args.program.upper() not in program:
            continue
        print(f"{program or '— общеуниверситетские'} / {kind}")
        print(f"   {describe(group)}")
        if catalog:
            # Обязательные курсы плана свободную позицию не закрывают.
            required = frozenset(programs[program].courses) if program in programs else frozenset()
            codes = sorted(group.resolve(catalog, required, schools) - required)
            print(f"   курсов в каталоге: {len(codes)}")
            print(f"   {', '.join(codes) if codes else '—'}")


if __name__ == "__main__":
    main()


def core_categories(rows, admission_year: int) -> dict[str, ElectiveGroup]:
    """Чем закрываются общеуниверситетские позиции плана.

    В плане позиция названа категорией — "Kazakh Language", "Ethics", — и сама
    по себе не говорит, каким курсом её закрывают. Зато таблицы требований
    говорят, и одинаково у всех специальностей: "Kazakh | Two KAZ courses",
    "Ethics | One Ethics course (PHIL 210, 211 or 212)". Это утверждение
    handbook, а не догадка, и повторяется оно во всех выпусках.

    Элективы сюда не попадают: у них свои списки, свои у каждой специальности,
    и разбираются они отдельно.
    """
    collected: dict[str, ElectiveGroup] = {}
    for row in rows:
        source = normalize(f"{row.name} {row.explanation}")
        if row.section != "core" or row.is_total or not source:
            continue
        if ELECTIVE.search(source) or ANY_COURSES.search(source):
            continue

        subjects, _ = parse_subjects(source)
        codes = [ref.code for ref in row.courses if ref.code]
        if not subjects and not codes:
            continue

        key = normalize_title(row.name)
        if not key:
            continue
        group = collected.setdefault(
            key,
            ElectiveGroup(admission_year=admission_year, program="", kind=CORE),
        )
        group.courses.extend(CourseRef(code=code, title="") for code in codes)
        if subjects:
            group.rules.append(
                ElectiveRule(subjects=subjects, min_level=parse_min_level(source), raw=source)
            )
        group.notes.append(source)
    return collected


def match_category(name: str, categories: dict[str, ElectiveGroup]) -> ElectiveGroup | None:
    """Найти категорию, которой соответствует позиция плана.

    "Kazakh Language" в плане и "Kazakh" в таблице требований — одно и то же.
    Сравниваем по словам, а не по буквам: иначе "Ethics" совпадёт с
    "Bioethics", и позиция закроется курсом из чужой программы. Сначала
    пробуем самые подробные названия.
    """
    target = set(normalize_title(name).split())
    if not target:
        return None
    for key in sorted(categories, key=lambda k: -len(k.split())):
        words = set(key.split())
        if words and (words <= target or target <= words):
            return categories[key]
    return None
