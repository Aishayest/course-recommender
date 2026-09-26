"""Сборка программы студента поверх подготовленных данных.

Программа собирается из handbook года поступления и каталога курсов: на это
уходит около секунды, а меняется она только со сменой семестра. Поэтому
собранное держится в памяти — иначе каждая страница платила бы заново.
"""

from __future__ import annotations

from ..audit import Audit, audit
from ..data.assemble import Program, attach_catalog, attach_electives, load_programs
from ..data.prepare import Prepared
from ..data.transcripts import Transcript

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


def forget_built() -> None:
    """Сбросить собранное — нужно после обновления данных."""
    _built.clear()
