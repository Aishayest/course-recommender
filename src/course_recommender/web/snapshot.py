"""Статический снимок страниц — для показа без сервера.

GitHub Pages и подобные раздают только файлы: запустить питон там негде,
поэтому загрузка транскрипта и пересчёт на них работать не будут. Но сами
страницы можно отрисовать настоящим приложением на настоящих данных и
сохранить как HTML — этого хватает, чтобы показать черновик.

Студент здесь выдуманный, и это принципиально: университетские данные
открыты, а чей-то транскрипт — нет, и класть его по публичному адресу
нельзя даже с согласия владельца.

    uv run python -m course_recommender.web.snapshot -o docs
"""

from __future__ import annotations

import re
from pathlib import Path

# Какие страницы снимаем и под какими именами кладём.
PAGES = {
    "index.html": "/audit",
    "courses.html": "/courses",
    "plan.html": "/plan",
    "course.html": "/course/CSCI 231",
    "upload.html": "/",
}
LINKS = (("/audit", "index.html"), ("/courses", "courses.html"), ("/plan", "plan.html"))
TITLE = "Course Recommender NU"
BANNER = """
<div style="padding: 10px 40px; background: #1b1e24; color: #f4f2ec; font-size: 13px;
            font-family: 'Onest', system-ui, sans-serif; display: flex; gap: 10px;
            flex-wrap: wrap; align-items: baseline">
  <strong>Статический снимок</strong>
  <span style="opacity: .75">Данные курсов настоящие, студент выдуманный. Загрузка
  транскрипта, ползунки и выбор секции здесь не работают — это черновик интерфейса.</span>
</div>"""

# Выдуманный студент: специальность и коды курсов настоящие, человек — нет.
DEMO = [
    ("Fall 2023", [("MATH 161", "Calculus I", "A", 8), ("PHYS 161", "Physics I with Laboratory", "B+", 8),
                   ("CSCI 151", "Programming for Scientists and Engineers", "B", 8),
                   ("WCS 150", "Rhetoric and Composition", "B", 6)]),
    ("Spring 2024", [("MATH 162", "Calculus II", "B-", 8), ("HST 100", "History of Kazakhstan", "B", 6),
                     ("KAZ 356", "Kazakh Music History", "A-", 6),
                     ("CSCI 152", "Performance and Data Structures", "B", 8),
                     ("PHYS 162", "Physics II with Laboratory", "A-", 8)]),
    ("Fall 2024", [("CSCI 231", "Computer Systems and Organization", "C-", 6),
                   ("MATH 251", "Discrete Mathematics", "B-", 6),
                   ("WCS 200", "Introduction to Public Speaking", "B", 6),
                   ("MATH 273", "Linear Algebra with Applications", "A-", 8),
                   ("CSCI 235", "Programming Languages", "C+", 8)]),
    ("Spring 2025", [("CSCI 270", "Algorithms", "B-", 6), ("BUS 101", "Core Course in Business", "A", 6),
                     ("CSCI 272", "Formal Languages", "C", 6),
                     ("ROBT 206", "Microcontrollers with Lab", "A-", 8),
                     ("MATH 321", "Probability", "B+", 6)]),
    ("Fall 2025", [("CSCI 390", "Artificial Intelligence", "B", 6),
                   ("CSCI 341", "Database Systems", "B+", 6),
                   ("BIOL 101", "Introductory Biology", "B", 6),
                   ("KAZ 313", "Kazakh for Business", "A-", 6),
                   ("CSCI 361", "Software Engineering", "B+", 6)]),
    ("Spring 2026", [("CSCI 333", "Computer Networks", "B-", 6), ("PHIL 210", "Ethics", "B", 6),
                     ("CHEM 100", "Introduction to Chemistry", "B", 6),
                     ("CSCI 332", "Operating Systems", "C+", 6),
                     ("CSCI 307", "Research Methods", "B+", 6),
                     ("CSCI 262", "Software Project Management", "A-", 6)]),
    ("Summer 2026", [("CSCI 299", "Internship I", "I*", 6)]),
]


def demo_transcript() -> str:
    """Текст транскрипта выдуманного студента."""
    from ..domain import GRADE_POINTS

    lines = [
        "NAZARBAYEV UNIVERSITY",
        "Student Unofficial Transcript",
        "Student Name: Aisha Demo",
        "Student ID: 202100000",
        "School: School of Computing and Artificial Intelligence",
        "Primary major: Computer Science",
        "Admission semester: Fall 2023",
    ]
    earned = 0
    for term, courses in DEMO:
        lines += [term, "Course Code Course Title Grade"]
        for code, title, grade, credits in courses:
            points = GRADE_POINTS.get(grade.rstrip("*"))
            lines.append(f"{code} {title} {grade} {credits} {points if points else 'n/a'}")
            if points:
                earned += credits
        lines.append("Semester GPA: 3.10 Credits Enrolled: 30 Credits Earned: 30")
    lines += ["Overall", f"GPA: 3.08 Credits Enrolled: {earned + 6} Credits Earned: {earned}"]
    return "\n".join(lines)


def as_pdf(text: str) -> bytes:
    """Минимальный PDF с этим текстом.

    Приложение принимает только PDF, а держать в репозитории чужой файл
    незачем: проще собрать свой из строк.
    """
    stream = "BT /F1 10 Tf 1 0 0 1 20 760 Tm 12 TL\n"
    for line in text.split("\n"):
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream += f"({escaped}) Tj T*\n"
    stream += "ET"

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    return out.encode("latin-1")


def localize(html: str, name: str) -> str:
    """Переписать ссылки на соседние файлы вместо маршрутов приложения."""
    for route, file in LINKS:
        html = html.replace(f'href="{route}"', f'href="{file}"')
    html = re.sub(r'href="[^"]*?/static/app\.css"', 'href="app.css"', html)
    html = re.sub(r'href="/course/[^"]*"', 'href="course.html"', html)
    html = html.replace('href="/"', 'href="upload.html"')
    # Абсолютные адреса тестового клиента: без этого страница ищет стили на чужом хосте.
    html = html.replace("http://testserver/", "")
    # Формы на статике не работают — пусть никуда и не ведут.
    html = re.sub(r'action="/\w*"', 'action="#"', html)
    html = html.replace("<body>", "<body>" + BANNER, 1)
    if name == "index.html":
        html = re.sub(r"<title>[^<]*</title>", f"<title>{TITLE}</title>", html)
    return html


def render(destination: Path) -> list[Path]:
    """Отрисовать страницы и сложить рядом со стилями."""
    from fastapi.testclient import TestClient

    from .app import app

    destination.mkdir(parents=True, exist_ok=True)
    written = []
    with TestClient(app) as client:
        client.post(
            "/transcript",
            files={"pdf": ("demo.pdf", as_pdf(demo_transcript()), "application/pdf")},
        )
        for name, route in PAGES.items():
            path = destination / name
            path.write_text(localize(client.get(route).text, name), encoding="utf-8")
            written.append(path)

    styles = Path(__file__).parent / "static" / "app.css"
    target = destination / "app.css"
    target.write_text(styles.read_text(encoding="utf-8"), encoding="utf-8")
    written.append(target)
    return written


def main() -> None:
    import argparse

    from ..config import ROOT

    parser = argparse.ArgumentParser(description="Сохранить страницы как статический сайт")
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "docs")
    args = parser.parse_args()

    for path in render(args.output):
        print(f"   {path.stat().st_size / 1024:6.1f} КБ  {path.name}")
    print(f"-> {args.output}")


if __name__ == "__main__":
    main()
