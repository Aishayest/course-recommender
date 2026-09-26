"""Разбор транскрипта студента.

Транскрипт студент выгружает сам, и это единственный источник, где написано,
что он на самом деле прошёл и с какой оценкой. До него система исходила из
допущения "шёл строго по плану", а по плану не идёт почти никто: курсы
пересдают, берут не в свой семестр, закрывают элективом не то, что сосед.

Персональные данные: в репозиторий не попадают, разбор идёт локально.

Формат — текстовый PDF Registrar, по семестрам:

    Fall 2023
    Course Code Course Title Grade Credits ECTS Grade Points
    MATH 161 Calculus I A 8 4
    Semester GPA: 3.09 Credits Enrolled: 30 Credits Earned: 30

Длинные названия переносятся на следующую строку, а незачтённый курс стоит
с оценкой "I*" и баллами "n/a" — такой курс не пройден, и в кредиты он не идёт.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..domain import GRADE_POINTS, CompletedCourse, Student

TERM = re.compile(r"^(Fall|Spring|Summer)\s+(\d{4})$")
FIELD = re.compile(r"^(Student Name|Student ID|School|Primary major|Admission semester):\s*(.+)$")
# MATH 161 Calculus I A 8 4 — код, название, оценка, кредиты ECTS, баллы
COURSE = re.compile(
    r"^([A-Z]{2,5}\s?\d{3}[A-Za-z]?)\s+(.+?)\s+([A-Z][+\-*]?)\s+(\d{1,2})\s+([\d.]+|n/a)$"
)
SEMESTER_TOTAL = re.compile(r"^Semester GPA:\s*([\d.]+)")
OVERALL = re.compile(r"GPA:\s*([\d.]+)\s*Credits Enrolled:\s*(\d+)\s*Credits Earned:\s*(\d+)")
SEASON_OFFSET = {"Fall": 1, "Spring": 0, "Summer": 0}

# В транскрипте школа названа полностью, а в документах регистрации — кодом.
SCHOOL_CODES = {
    "school of computing and artificial intelligence": "SCAI",
    "school of engineering and digital sciences": "SEDS",
    "school of engineering": "SoE",
    "school of sciences and humanities": "SSH",
    "school of medicine": "SoM",
    "graduate school of business": "GSB",
    "school of mining and geosciences": "SMG",
}


@dataclass
class Transcript:
    """Разобранный транскрипт."""

    student_id: str = ""
    name: str = ""
    school: str = ""
    major: str = ""
    admission_term: str = ""
    courses: list[CompletedCourse] = field(default_factory=list)
    gpa: float | None = None
    credits_enrolled: int | None = None
    credits_earned: int | None = None

    @property
    def admission_year(self) -> int | None:
        """Год поступления — ключ к нужному выпуску handbook."""
        match = TERM.match(self.admission_term)
        return int(match.group(2)) if match else None

    @property
    def school_code(self) -> str:
        return SCHOOL_CODES.get(self.school.strip().lower(), self.school)

    @property
    def earned(self) -> int:
        """Кредиты по разобранным курсам."""
        return sum(course.credits for course in self.courses if course.is_earned)

    @property
    def is_partial(self) -> bool:
        """В файл попали не все страницы транскрипта.

        Итоговая строка считает по всему транскрипту целиком. Если сумма по
        разобранным курсам меньше, значит часть семестров осталась в другом
        файле. Строить по такому аудит нельзя: он объявит непройденными
        курсы, которые студент прошёл.
        """
        return self.credits_earned is not None and self.earned < self.credits_earned

    @property
    def terms(self) -> tuple[str, ...]:
        seen = {course.term for course in self.courses if course.term}
        return tuple(sorted(seen, key=term_order))

    @property
    def last_semester(self) -> int:
        return max((course.semester for course in self.courses), default=0)

    @property
    def next_semester(self) -> int:
        """Семестр, который студенту предстоит."""
        return self.last_semester + 1

    def student(self) -> Student:
        """Доменный студент.

        Курс обучения — тот, на котором студент будет в следующем семестре,
        а не тот, который он закончил: тиры приоритета выдаются под
        предстоящую регистрацию. Закрыв шестой семестр, он регистрируется
        уже как четверокурсник.
        """
        return Student(
            student_id=self.student_id or "student",
            major=self.major,
            year=max(1, (self.next_semester + 1) // 2),
            gpa=self.gpa or 0.0,
            completed=list(self.courses),
        )


def term_order(term: str) -> tuple[int, int]:
    match = TERM.match(term)
    if not match:
        return (0, 0)
    return (int(match.group(2)), {"Spring": 0, "Summer": 1, "Fall": 2}[match.group(1)])


def semester_number(term: str, admission_term: str) -> int:
    """Номер семестра сквозной нумерацией плана, 1..8.

    Лето своего номера не получает: в учебном плане его нет, и курс,
    взятый летом, относится к тому же номеру, что и предыдущая весна.
    """
    current, admission = TERM.match(term), TERM.match(admission_term)
    if not current or not admission:
        return 0
    years = int(current.group(2)) - int(admission.group(2))
    number = years * 2 + SEASON_OFFSET[current.group(1)]
    # Поступившим весной первый семестр — их весна, а не предыдущая осень.
    if admission.group(1) != "Fall":
        number += 1
    return max(1, number)


def parse_grade(letter: str) -> float | None:
    """Балл по буквенной оценке. None — результата нет: "I" (незачёт), "W"."""
    return GRADE_POINTS.get(letter.rstrip("*"))


def normalize_code(code: str) -> str:
    return re.sub(r"\s+", " ", code).strip()


def parse_text(text: str) -> Transcript:
    """Разобрать текст транскрипта."""
    transcript = Transcript()
    term = ""
    lines = [line.strip() for line in text.split("\n")]

    for line in lines:
        header = FIELD.match(line)
        if header:
            key, value = header.group(1), header.group(2).strip()
            if key == "Student Name":
                transcript.name = value
            elif key == "Student ID":
                transcript.student_id = value
            elif key == "School":
                transcript.school = value
            elif key == "Primary major":
                transcript.major = value
            elif key == "Admission semester":
                transcript.admission_term = value
            continue

        if TERM.match(line):
            term = line
            continue

        course = COURSE.match(line)
        if course and term:
            code, title, letter, credits, _points = course.groups()
            transcript.courses.append(
                CompletedCourse(
                    code=normalize_code(code),
                    grade=parse_grade(letter),
                    semester=semester_number(term, transcript.admission_term),
                    credits=int(credits),
                    title=title.strip(),
                    term=term,
                )
            )
            continue

        if SEMESTER_TOTAL.match(line):
            continue

        overall = OVERALL.search(line)
        if overall and line.lstrip().startswith("GPA:"):
            transcript.gpa = float(overall.group(1))
            transcript.credits_enrolled = int(overall.group(2))
            transcript.credits_earned = int(overall.group(3))

    return transcript


def parse_stream(source) -> Transcript:
    """Разобрать транскрипт из открытого файла или буфера в памяти.

    Загруженный через браузер файл на диск класть незачем: это персональные
    данные, и чем меньше их следов, тем лучше.
    """
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return parse_text(text)


def parse_pdf(path: Path) -> Transcript:
    """Разобрать транскрипт из PDF."""
    return parse_stream(path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Разобрать транскрипт студента")
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args()

    transcript = parse_pdf(args.transcript)
    print(f"{transcript.name or '—'}, {transcript.major or '—'} ({transcript.school_code})")
    print(f"поступление: {transcript.admission_term}, семестров: {len(transcript.terms)}")
    print(
        f"курсов: {len(transcript.courses)}, кредитов набрано: {transcript.earned}"
        + (f" (в транскрипте {transcript.credits_earned})" if transcript.credits_earned else "")
    )
    print(f"GPA: {transcript.gpa}")
    if transcript.is_partial:
        print("ВНИМАНИЕ: в файле не все страницы транскрипта")
    for term in transcript.terms:
        courses = [c for c in transcript.courses if c.term == term]
        print(f"\n--- {term} (семестр {courses[0].semester})")
        for course in courses:
            grade = f"{course.grade:.2f}" if course.grade is not None else "нет"
            print(f"   {course.code:10s} {course.credits:2d} ECTS  балл {grade:5s} {course.title[:44]}")


if __name__ == "__main__":
    main()
