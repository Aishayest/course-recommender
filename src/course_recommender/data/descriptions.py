"""Описания курсов из публичного каталога Registrar.

Ни handbook, ни документ регистрации, ни расписание не говорят, о чём курс, —
везде только название. Из-за этого система не отличала один технический
электив от другого: все закрывают ту же позицию, дают те же кредиты, и
выбирать приходилось по остаточному признаку.

Каталог на сайте Registrar это закрывает. Страница рисуется скриптом, но
ходит она в обычный JSON-метод, и описание приходит прямо в результатах
поиска — отдельный запрос на каждый курс не нужен.

    uv run python -m course_recommender.data.descriptions -o data/processed/descriptions.json

Выгрузка идёт страницами по 500 записей с паузой между ними: каталог
публичный, но долбить его незачем.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

CATALOG_URL = "https://registrar.nu.edu.kz/my-registrar/public-course-catalog/json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
PAGE_SIZE = 500
PAUSE_SECONDS = 1.0
# Каталог пишет "n/a" там, где описания нет. Пустая строка честнее.
MISSING = {"", "n/a", "N/A", "-"}
UNDERGRADUATE = "Undergraduate"
# Ссылка на промежуточный сертификат внутри самого сертификата сервера.
ISSUER_URL = re.compile(rb"https?://[^\x00-\x20\"'<>]+?\.crt")


@dataclass(frozen=True)
class CourseDescription:
    """Что каталог рассказывает о курсе."""

    code: str
    title: str
    description: str = ""
    credits_ects: int | None = None
    level: str = ""
    school: str = ""
    department: str = ""
    breadth: str = ""
    prerequisite: str = ""
    corequisite: str = ""
    antirequisite: str = ""
    last_taught: str = ""

    @property
    def is_undergraduate(self) -> bool:
        return self.level == UNDERGRADUATE

    @property
    def has_description(self) -> bool:
        return bool(self.description)

    @property
    def text(self) -> str:
        """Название и описание одной строкой — то, что читает модель.

        Название входит всегда: у 7% курсов описания нет вовсе, и без
        названия про них было бы не известно ничего.
        """
        return f"{self.title}. {self.description}".strip(". ").strip()


@dataclass
class Descriptions:
    """Каталог описаний по кодам курсов."""

    courses: dict[str, CourseDescription] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.courses)

    def __contains__(self, code: str) -> bool:
        return code in self.courses

    def get(self, code: str) -> CourseDescription | None:
        """Описание курса.

        Курс, который читают две кафедры сразу, в наших документах записан
        одним кодом через косую черту — "ANT 204/PLS 204", — а в каталоге
        Registrar лежит двумя отдельными записями. Поэтому составной код
        разбирается на части.
        """
        found = self.courses.get(code)
        if found is not None:
            return found
        for part in code.split("/"):
            found = self.courses.get(part.strip())
            if found is not None:
                return found
        return None

    @property
    def undergraduate(self) -> dict[str, CourseDescription]:
        return {code: c for code, c in self.courses.items() if c.is_undergraduate}

    def texts(self, codes=None) -> dict[str, str]:
        """Тексты курсов для модели: код -> название с описанием."""
        chosen = self.courses if codes is None else {
            code: self.courses[code] for code in codes if code in self.courses
        }
        return {code: course.text for code, course in chosen.items() if course.text}


def _clean(value) -> str:
    text = (value or "").strip()
    return "" if text in MISSING else " ".join(text.split())


def _number(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_entry(row: dict) -> CourseDescription | None:
    """Разобрать одну запись каталога."""
    code = _clean(row.get("ABBR"))
    if not code:
        return None
    return CourseDescription(
        code=code,
        title=_clean(row.get("TITLE")),
        description=_clean(row.get("SHORTDESC")),
        credits_ects=_number(row.get("CRECTS")),
        level=_clean(row.get("ACADEMICLEVEL")),
        school=_clean(row.get("SCHOOLABBR")) or _clean(row.get("SCHOOL")),
        department=_clean(row.get("DEPARTMENT")),
        breadth=_clean(row.get("BREADTH")),
        prerequisite=_clean(row.get("PREREQ")),
        corequisite=_clean(row.get("COREQ")),
        antirequisite=_clean(row.get("ANTIREQ")),
        last_taught=_clean(row.get("TERMNAME")),
    )


def _server_certificate(host: str, port: int = 443, timeout: int = 20) -> bytes | None:
    """Сертификат сервера как есть, без проверки.

    Проверять здесь нечего: сертификат берут ровно затем, чтобы прочитать
    из него ссылку на недостающее звено цепочки. Данные по этому соединению
    не ходят.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with (
            socket.create_connection((host, port), timeout=timeout) as raw,
            context.wrap_socket(raw, server_hostname=host) as sock,
        ):
            return sock.getpeercert(binary_form=True)
    except OSError:
        return None


def _missing_intermediate(host: str, timeout: int = 20) -> str | None:
    """Достать промежуточный сертификат, который сервер не прислал.

    Registrar отдаёт только свой сертификат, без выпустившего его
    промежуточного, и проверка цепочки обрывается. Браузер и curl в таком
    случае скачивают недостающее звено по ссылке из самого сертификата;
    Python так не умеет, поэтому делаем это руками. Доверие от этого не
    страдает: промежуточный всё равно проверяется по корневому из certifi.
    """
    certificate = _server_certificate(host, timeout=timeout)
    match = ISSUER_URL.search(certificate or b"")
    if not match:
        return None
    request = urllib.request.Request(match.group(0).decode(), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return ssl.DER_cert_to_PEM_cert(response.read())
    except (OSError, ValueError):
        return None


def _bundle_path() -> Path:
    from ..config import DATA_INTERIM

    return DATA_INTERIM / "registrar-chain.pem"


def _ssl_context(host: str = "registrar.nu.edu.kz") -> ssl.SSLContext:
    """Контекст проверки сертификатов.

    Python с python.org не видит системные сертификаты macOS, поэтому корни
    берутся из certifi. Если и с ними цепочка не сходится, к ним добавляется
    промежуточный сертификат, которого не прислал сервер.
    """
    try:
        import certifi

        roots = Path(certifi.where())
    except ImportError:
        return ssl.create_default_context()

    bundle = _bundle_path()
    if bundle.exists():
        return ssl.create_default_context(cafile=str(bundle))

    context = ssl.create_default_context(cafile=str(roots))
    if _server_certificate(host) is not None:
        try:
            with socket.create_connection((host, 443), timeout=20) as raw:
                context.wrap_socket(raw, server_hostname=host).close()
            return context
        except ssl.SSLCertVerificationError:
            pass

    intermediate = _missing_intermediate(host)
    if not intermediate:
        return context

    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(roots.read_text(encoding="utf-8") + "\n" + intermediate, encoding="utf-8")
    return ssl.create_default_context(cafile=str(bundle))


def fetch_page(page: int, limit: int = PAGE_SIZE, timeout: int = 60) -> tuple[list[dict], int]:
    """Одна страница каталога: записи и общее число курсов."""
    params = {
        "method": "getSearchData",
        "searchParams[formSimple]": "false",
        "searchParams[limit]": str(limit),
        "searchParams[page]": str(page),
        "searchParams[start]": "0",
        "searchParams[quickSearch]": "",
        "searchParams[sortField]": "-1",
        "searchParams[sortDescending]": "-1",
        "searchParams[semester]": "-1",
        "searchParams[credit][type]": "",
        "searchParams[credit][from]": "",
        "searchParams[credit][to]": "",
    }
    request = urllib.request.Request(
        CATALOG_URL,
        data=urllib.parse.urlencode(params).encode(),
        headers={"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
    )
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return payload.get("data") or [], int(payload.get("total") or 0)


def fetch_all(limit: int = PAGE_SIZE, pause: float = PAUSE_SECONDS, progress=None) -> Descriptions:
    """Выгрузить каталог целиком."""
    catalog = Descriptions()
    page, total = 1, None
    while True:
        rows, reported = fetch_page(page, limit)
        total = total or reported
        for row in rows:
            entry = parse_entry(row)
            if entry is not None:
                catalog.courses[entry.code] = _better(catalog.courses.get(entry.code), entry)
        if progress:
            progress(len(catalog), total)
        if not rows or len(catalog) >= total or page * limit >= total:
            break
        page += 1
        time.sleep(pause)
    return catalog


def _better(current: CourseDescription | None, candidate: CourseDescription) -> CourseDescription:
    """Какую из двух записей одного курса оставить.

    Курс встречается в каталоге по разу на семестр, и описание заполнено не
    везде. Побеждает запись с описанием: пустая ничего не добавляет, а
    потерять текст из-за порядка выдачи было бы обидно.
    """
    if current is None:
        return candidate
    if candidate.has_description and not current.has_description:
        return candidate
    if current.has_description and not candidate.has_description:
        return current
    return max(current, candidate, key=lambda c: len(c.description))


def to_json(catalog: Descriptions) -> list[dict]:
    return [
        {
            "code": course.code,
            "title": course.title,
            "description": course.description,
            "credits_ects": course.credits_ects,
            "level": course.level,
            "school": course.school,
            "department": course.department,
            "breadth": course.breadth,
            "prerequisite": course.prerequisite,
            "corequisite": course.corequisite,
            "antirequisite": course.antirequisite,
            "last_taught": course.last_taught,
        }
        for course in sorted(catalog.courses.values(), key=lambda c: c.code)
    ]


def from_json(payload: list[dict]) -> Descriptions:
    catalog = Descriptions()
    for item in payload:
        catalog.courses[item["code"]] = CourseDescription(**item)
    return catalog


def save(catalog: Descriptions, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json(catalog), ensure_ascii=False, indent=2), encoding="utf-8")


def load(path: Path) -> Descriptions:
    return from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def default_path() -> Path:
    from ..config import DATA_PROCESSED

    return DATA_PROCESSED / "descriptions.json"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Выгрузить описания курсов из каталога Registrar")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=PAGE_SIZE, help="записей за запрос")
    parser.add_argument("--pause", type=float, default=PAUSE_SECONDS, help="пауза между запросами")
    args = parser.parse_args()

    def show(done: int, total: int) -> None:
        print(f"   {done} из {total}")

    print("выгрузка каталога...")
    catalog = fetch_all(args.limit, args.pause, progress=show)
    described = [c for c in catalog.courses.values() if c.has_description]
    undergraduate = catalog.undergraduate

    print(f"курсов: {len(catalog)}, с описанием: {len(described)}")
    print(f"бакалавриат: {len(undergraduate)}")

    output = args.output or default_path()
    save(catalog, output)
    print(f"-> {output}")


if __name__ == "__main__":
    main()
