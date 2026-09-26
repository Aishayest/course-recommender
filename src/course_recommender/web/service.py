"""Сборка программы студента поверх подготовленных данных.

Программа собирается из handbook года поступления и каталога курсов: на это
уходит около секунды, а меняется она только со сменой семестра. Поэтому
собранное держится в памяти — иначе каждая страница платила бы заново.
"""

from __future__ import annotations

from ..audit import Audit, audit
from ..config import UTILITY_WEIGHTS
from ..data.assemble import Program, attach_catalog, attach_electives, load_programs
from ..data.prepare import Prepared
from ..data.transcripts import Transcript
from ..recommend import Recommendation, recommend

# Собранные программы по паре "год поступления + семестр".
_built: dict[tuple[int, str | None], dict[str, Program]] = {}


def programs_for(year: int, data: Prepared, term: str | None = None) -> dict[str, Program]:
    """Все специальности этого года поступления, дополненные каталогом.

    Выпуска handbook за этот год может не быть выгружено вовсе — тогда
    программ нет, и это честный ответ: подставлять план чужого года нельзя,
    у каждого потока свои требования.
    """
    key = (year, term)
    if key not in _built:
        try:
            programs = load_programs(year)
        except (FileNotFoundError, OSError):
            programs = {}
        if programs and len(data.catalog):
            attach_catalog(programs, data.catalog, term)
            attach_electives(programs, data.catalog, term)
        _built[key] = programs
    return _built[key]


def program_of(
    transcript: Transcript, data: Prepared, term: str | None = None
) -> Program | None:
    """Программа студента. None — handbook такой специальности не знает."""
    year, name = transcript.admission_year, transcript.major
    if not year or not name:
        return None
    programs = programs_for(year, data, term)
    return next((p for key, p in programs.items() if name.upper() in key), None)


def audit_of(
    transcript: Transcript, data: Prepared, term: str | None = None
) -> tuple[Program, Audit] | None:
    """Что студенту осталось до диплома."""
    program = program_of(transcript, data, term)
    if program is None:
        return None
    return program, audit(program, transcript.student())


def relevance_of(transcript: Transcript, data: Prepared) -> dict:
    """Близость курсов к тому, что студенту уже заходило.

    Пусто, если векторов не подготовлено: тогда слой релевантности просто
    не участвует, а не подставляет нули.
    """
    if data.vectors is None or not len(data.vectors):
        return {}

    from dataclasses import replace as replace_field

    from ..models.embeddings import affinities, rescale

    found = affinities(transcript.student(), data.vectors)
    scores = rescale({code: value.score for code, value in found.items()})
    return {
        code: replace_field(value, score=scores[code])
        for code, value in found.items()
        if code in scores
    }


def recommendations_for(
    transcript: Transcript,
    data: Prepared,
    term: str | None = None,
    weights: dict | None = None,
    limit: int = 20,
) -> tuple[Program, Audit, list[Recommendation]] | None:
    """Что студенту стоит взять в следующем семестре.

    Список открытых позиций берётся из аудита, а не из плана: студент,
    который идёт не по расписанию handbook, иначе получил бы курсы под
    позиции, давно закрытые.
    """
    found = audit_of(transcript, data, term)
    if found is None:
        return None

    program, result = found
    student = transcript.student()
    results = recommend(
        program,
        student,
        transcript.next_semester,
        offerings=data.catalog.entries,
        fill_history=data.fill_history,
        sections=data.sections(term),
        school=transcript.school_code,
        term=term,
        availability=data.availability,
        grades=data.grades,
        weights=weights or UTILITY_WEIGHTS,
        slots=[status.slot for status in result.open_slots],
        fit=relevance_of(transcript, data),
        limit=limit,
    )
    return program, result, results


def plan_for(
    transcript: Transcript,
    data: Prepared,
    term: str | None = None,
    weights: dict | None = None,
    prefer: dict[str, str] | None = None,
):
    """Собрать семестр: курсы, секции и время, без пересечений."""
    from collections import Counter

    from ..plan import assemble, target_credits

    found = recommendations_for(transcript, data, term, weights, limit=24)
    if found is None:
        return None

    program, result, results = found
    open_slots = [status.slot for status in result.open_slots]
    capacity = dict(Counter(slot.name for slot in open_slots)) or None
    semester = assemble(
        [item.evidence for item in results],
        data.sections(term),
        target_credits(program, transcript.next_semester),
        term or "",
        capacity,
        prefer,
    )
    return program, semester


def forget_built() -> None:
    """Сбросить собранное — нужно после обновления данных."""
    _built.clear()
