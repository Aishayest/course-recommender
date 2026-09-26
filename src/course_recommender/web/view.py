"""Подготовка разобранного к показу.

Здесь только перевод доменных объектов в то, что читает шаблон: строки,
подписи и пометки. Никаких решений о курсах — они приняты слоями ниже.
"""

from __future__ import annotations

from ..audit import Audit
from ..data.transcripts import TERM, Transcript

# Разделы интерфейса в порядке, в котором студент через них проходит.
SECTIONS = (
    ("audit", "Аудит", "/audit"),
    ("courses", "Рекомендации", "/courses"),
)

# Состояния позиции программы. Порядок — от выполненного к неизвестному,
# в нём же они показываются в легенде.
STATES = {
    "closed": "закрыта",
    "missing": "не пройден",
    "retake": "ниже проходной",
    "current": "идёт сейчас",
    "open": "открыта, есть варианты",
    "any": "открыта, любой курс",
    "unverified": "не проверена",
}
SEASONS = {True: "Fall", False: "Spring"}


def student_chip(transcript: Transcript) -> dict:
    """Шапка: кто это и по какой программе учится."""
    parts = [transcript.major, transcript.school_code]
    if transcript.admission_term:
        parts.append(f"с {transcript.admission_term}")
    if transcript.gpa is not None:
        parts.append(f"GPA {transcript.gpa}")
    return {
        "name": transcript.name,
        "facts": " · ".join(part for part in parts if part),
    }


def partial_transcript_error(filename: str, transcript: Transcript) -> dict:
    """Экран отказа: в файл попала не вся выгрузка.

    Разбирать такой транскрипт нельзя — аудит объявит непройденными курсы,
    которые студент прошёл. Показываем обе цифры: по итоговой строке файла
    и по тому, что удалось собрать.
    """
    return {
        "filename": filename,
        "title": "Загрузите транскрипт целиком",
        "text": (
            "Похоже, в файл попала только часть выгрузки. Если продолжить, система "
            "посчитает непройденными курсы, которые вы на самом деле прошли, — "
            "поэтому мы остановились."
        ),
        "figures": [
            {"label": "в итоговой строке", "value": f"{transcript.credits_earned} ECTS"},
            {"label": "нашли по курсам", "value": f"{transcript.earned} ECTS", "problem": True},
            {"label": "семестров в файле", "value": str(len(transcript.terms))},
        ],
    }


def unreadable_error(filename: str) -> dict:
    """Экран отказа: это не транскрипт или он нечитаемый."""
    return {
        "filename": filename,
        "title": "Не удалось прочитать транскрипт",
        "text": (
            "В файле не нашлось ни одного курса. Нужен неофициальный транскрипт "
            "из личного кабинета Registrar, сохранённый как PDF, — не скан и не "
            "снимок экрана."
        ),
        "figures": [],
    }


def transcript_summary(transcript: Transcript) -> dict:
    """Что разобрали — чтобы студент убедился, что файл тот."""
    return {
        "name": transcript.name,
        "student_id": transcript.student_id,
        "major": transcript.major,
        "school": transcript.school_code,
        "admission": transcript.admission_term,
        "gpa": transcript.gpa,
        "earned": transcript.earned,
        "courses": len(transcript.courses),
        "next_semester": transcript.next_semester,
        "terms": [
            {
                "term": term,
                "courses": [
                    {
                        "code": course.code,
                        "title": course.title,
                        "credits": course.credits,
                        "grade": f"{course.grade:.2f}" if course.grade is not None else None,
                    }
                    for course in transcript.courses
                    if course.term == term
                ],
            }
            for term in transcript.terms
        ],
    }


def term_of(admission_term: str, semester: int) -> str:
    """Какой это был семестр по календарю.

    Первый семестр — тот, в который студент поступил, дальше чередуются
    осень и весна. Лето в нумерации плана не участвует.
    """
    match = TERM.match(admission_term or "")
    if not match or semester < 1:
        return ""
    year = int(match.group(2))
    odd = semester % 2 == 1
    if match.group(1) == "Fall":
        # Осень, весна следующего года, снова осень: учебный год переходит
        # через календарный, поэтому у весенних семестров год на единицу больше.
        return f"{SEASONS[odd]} {year + (semester - 1) // 2 + (0 if odd else 1)}"
    # Поступившим весной проще: весна и следующая за ней осень — один год.
    return f"{SEASONS[not odd]} {year + (semester - 1) // 2}"


def _course_state(code: str, result: Audit) -> str:
    """Что стало с обязательным курсом плана."""
    if any(course.code == code for course in result.done):
        return "closed"
    if any(course.code == code for course, _ in result.low_grade):
        return "retake"
    if any(course.code == code for course in result.in_progress):
        return "current"
    return "missing"


def _slot_state(status) -> str:
    """Что стало со свободной позицией плана."""
    if status.is_closed:
        return "closed"
    if status.slot.eligible_codes:
        return "open"
    if status.is_checkable:
        return "any"
    return "unverified"


def _slot_detail(status) -> str:
    if status.is_closed:
        return f"закрыт {status.closed_by}"
    if status.slot.eligible_codes:
        return f"{len(status.slot.eligible_codes)} вариантов"
    if status.is_checkable:
        return "закрывается любым курсом"
    return "handbook не говорит, чем закрывается"


def program_map(result: Audit, transcript: Transcript) -> list[dict]:
    """Карта программы: восемь семестров, в каждом — позиции с их состоянием.

    Ключ называется cells, а не items: в шаблоне `column.items` разрешилось
    бы в метод словаря, а не в значение.
    """
    columns = []
    for semester in range(1, 9):
        cells = [
            {
                "name": course.code,
                "sub": course.title[:42] or f"{course.credits} ECTS",
                "state": _course_state(course.code, result),
            }
            for course in sorted(
                (c for c in result.program.courses.values() if c.recommended_semester == semester),
                key=lambda c: c.code,
            )
        ]
        cells += [
            {
                "name": status.slot.name,
                "sub": _slot_detail(status),
                "state": _slot_state(status),
            }
            for status in result.slots
            if status.slot.semester == semester
        ]
        if cells:
            columns.append(
                {
                    "name": f"Семестр {semester}",
                    "term": term_of(transcript.admission_term, semester),
                    "cells": cells,
                }
            )
    return columns


def audit_page(result: Audit, transcript: Transcript) -> dict:
    """Всё, что показывает страница аудита."""
    in_progress_credits = sum(course.credits for course in result.in_progress)
    total = result.degree_credits or 0
    open_slots = [status for status in result.open_slots if status.is_checkable]
    unchecked = result.unchecked_slots

    attention = [
        {
            "code": course.code,
            "state": "retake",
            "title": course.title,
            "detail": (
                f"оценка {grade:.2f} — ниже проходной {course.min_grade} · "
                f"{course.recommended_semester} семестр плана"
            ),
        }
        for course, grade in result.low_grade
    ] + [
        {
            "code": course.code,
            "state": "missing",
            "title": course.title,
            "detail": f"обязательный · {course.recommended_semester} семестр плана · {course.credits} ECTS",
        }
        for course in result.missing
    ] + [
        {
            "code": course.code,
            "state": "current",
            "title": course.title,
            "detail": "без оценки · в кредиты пока не входит",
        }
        for course in result.in_progress
    ]

    return {
        "program": result.program.name,
        "degree": result.program.degree,
        "admission": transcript.admission_term,
        "credits": {
            "earned": result.earned_credits,
            "in_progress": in_progress_credits,
            "total": total,
            "remaining": result.remaining_credits,
            "earned_share": round(result.earned_credits / total * 100, 1) if total else 0,
            "progress_share": round(in_progress_credits / total * 100, 1) if total else 0,
        },
        "tiles": [
            {"n": len(result.missing), "state": "missing", "label": "обязательных не пройдено",
             "sub": ", ".join(c.code for c in result.missing[:3]) or "всё сдано"},
            {"n": len(result.low_grade), "state": "retake", "label": "нужна пересдача",
             "sub": "пройден ниже проходной"},
            {"n": len(result.in_progress), "state": "current", "label": "идёт сейчас",
             "sub": "без оценки, в кредиты не входит"},
            {"n": len(open_slots), "state": "open", "label": "открытые позиции",
             "sub": "можно закрыть курсами"},
            {"n": len(unchecked), "state": "unverified", "label": "не проверено",
             "sub": "handbook не уточняет"},
        ],
        "legend": [{"state": state, "label": label} for state, label in STATES.items()],
        "map": program_map(result, transcript),
        "slots": [
            {
                "name": status.slot.name,
                "semester": status.slot.semester,
                "state": _slot_state(status),
                "status": STATES[_slot_state(status)],
                "detail": _slot_detail(status),
            }
            for status in result.slots
            if not status.is_closed
        ],
        "attention": attention,
        "extra": [
            {"code": course.code, "title": course.title, "credits": course.credits}
            for course in result.extra
        ],
        "complete": result.is_complete,
    }


# Из чего складывается итоговый балл. Порядок — как в формуле.
COMPONENTS = (
    ("need", "Нужность", "стоит в плане или закрывает позицию"),
    ("access", "Шанс попасть", "по тиру приоритета и заполняемости"),
    ("fit", "Близость по содержанию", "к пройденным курсам, с весом по оценке"),
    ("ease", "Оценки на курсе", "средний балл тех, кто его брал"),
)


def _components(evidence, weights: dict) -> list[dict]:
    """Слагаемые балла: сколько каждое весит и что известно.

    Слагаемое с нулевым весом показывается отдельно: оно посчитано, но в
    балл не вошло, и это решение, а не отсутствие данных.
    """
    values = {
        "need": (evidence.need, True),
        "access": (evidence.seat_chance, evidence.fill_chance is not None or evidence.mean_fill is not None),
        "fit": (evidence.fit, evidence.fit_score is not None),
        "ease": (evidence.ease, evidence.grades is not None and evidence.grades.average is not None),
    }
    shown = []
    for key, label, hint in COMPONENTS:
        value, known = values[key]
        weight = weights.get(key, 0.0)
        shown.append(
            {
                "key": key,
                "label": label,
                "hint": hint,
                "weight": weight,
                "counted": weight > 0,
                "known": known,
                "value": f"{value:.2f}",
                "percent": round(value * 100),
            }
        )
    return shown


def _warnings(evidence) -> list[dict]:
    """Что стоит знать до регистрации."""
    found = []
    if evidence.needs_permission:
        found.append({"kind": "warn", "text": "нужно согласие преподавателя"})
    if evidence.missing:
        found.append({"kind": "warn", "text": f"не хватает: {', '.join(evidence.missing)}"})
    if evidence.conflicts:
        found.append(
            {"kind": "warn", "text": f"пересекается по времени с {', '.join(evidence.conflicts)}"}
        )
    return found


def _access(evidence) -> dict:
    """Свидетельства о том, попадёт ли студент на курс."""
    tier = evidence.priority_tier
    return {
        "tier": f"тир {tier}" if tier else "приоритета нет",
        "tier_source": "из документа регистрации",
        "fill_known": evidence.mean_fill is not None,
        "fill": round((evidence.mean_fill or 0) * 100),
        "fill_source": (
            f"в среднем за {evidence.terms_observed} семестра"
            if evidence.terms_observed > 1
            else "по одному семестру"
        )
        if evidence.mean_fill is not None
        else "истории заполняемости нет",
        "chance": round(evidence.seat_chance * 100),
        "fill_chance_known": evidence.fill_chance is not None,
        "fill_chance": round((evidence.fill_chance or 0) * 100),
    }


def _grades(evidence) -> dict:
    """Чем курс заканчивался у тех, кто его брал."""
    stats = evidence.grades
    if stats is None or stats.average is None:
        return {"known": False, "source": "отчётов об оценках по этому курсу нет"}

    shares = stats.shares
    bad = shares.get("D", 0.0) + shares.get("F", 0.0) + shares.get("W", 0.0)
    spread = stats.spread()
    return {
        "known": True,
        "average": f"{stats.average:.2f}",
        "a": round(shares.get("A", 0.0)),
        "b": round(shares.get("B", 0.0)),
        "c": round(shares.get("C", 0.0)),
        "bad": round(bad),
        "spread": f"{spread:.2f}" if spread and spread >= 0.3 else None,
        "source": f"{', '.join(stats.terms)} · n={stats.graded}",
    }


def _teacher(evidence) -> dict:
    """Кто ведёт в этом семестре и чем это кончалось раньше."""
    if not evidence.instructors:
        return {"known": False, "note": "кто ведёт — в расписании не указано"}

    records = []
    for name in evidence.instructors:
        record = evidence.grades.record_of(name) if evidence.grades else None
        records.append(
            {
                "name": name,
                "known": record is not None,
                "average": f"{record.average:.2f}" if record else None,
                "n": record.graded if record else None,
            }
        )
    return {"known": True, "people": records}


def course_card(rank: int, result, weights: dict) -> dict:
    """Одна карточка рекомендации."""
    evidence = result.evidence
    course = result.course
    return {
        "rank": rank,
        "code": course.code,
        "title": course.title,
        "credits": course.credits,
        "score": f"{result.score:.2f}",
        "why": result.why,
        "closes": evidence.fills_slot,
        "on_plan": evidence.on_plan,
        "fit_closest": evidence.fit_closest,
        "warnings": _warnings(evidence),
        "components": _components(evidence, weights),
        "access": _access(evidence),
        "grades": _grades(evidence),
        "teacher": _teacher(evidence),
        "fallback": result.fallback.code if result.fallback else None,
    }


def courses_page(results, weights: dict, term: str | None, slots) -> dict:
    """Всё, что показывает страница рекомендаций."""
    return {
        "term": term,
        "count": len(results),
        "weights": {key: weights.get(key, 0.0) for key, _, _ in COMPONENTS},
        "controls": [
            {"key": key, "label": label, "hint": hint, "value": weights.get(key, 0.0)}
            for key, label, hint in COMPONENTS
        ],
        "slots": sorted({status.slot.name for status in slots}),
        "courses": [course_card(i, result, weights) for i, result in enumerate(results, start=1)],
    }
