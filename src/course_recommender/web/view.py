"""Подготовка разобранного к показу.

Здесь только перевод доменных объектов в то, что читает шаблон: строки,
подписи и пометки. Никаких решений о курсах — они приняты слоями ниже.
"""

from __future__ import annotations

from ..data.transcripts import Transcript

# Разделы интерфейса в порядке, в котором студент через них проходит.
SECTIONS = (("audit", "Аудит", "/audit"),)


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
