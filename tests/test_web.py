import pytest

fastapi = pytest.importorskip("fastapi", reason="веб-интерфейс ставится отдельным extra")

from fastapi.testclient import TestClient

from course_recommender.data.transcripts import parse_text
from course_recommender.web import view
from course_recommender.web.app import app, sessions
from course_recommender.web.state import COOKIE, Sessions

# Синтетический транскрипт: настоящие в репозиторий не попадают.
SAMPLE = """NAZARBAYEV UNIVERSITY
Student Unofficial Transcript
Student Name: Test Student
Student ID: 202100000
School: School of Computing and Artificial Intelligence
Primary major: Computer Science
Admission semester: Fall 2023
Fall 2023
Course Code Course Title Grade
MATH 161 Calculus I A 8 4
CSCI 151 Programming for Scientists and Engineers C 8 2
Semester GPA: 3.00 Credits Enrolled: 16 Credits Earned: 16
Spring 2024
Course Code Course Title Grade
CSCI 299 Internship I I* 6 n/a
Semester GPA: 0.0 Credits Enrolled: 6 Credits Earned: 0
Overall
GPA: 3.00 Credits Enrolled: 22 Credits Earned: 16
"""

# Минимальный настоящий PDF с текстом: генерировать его проще, чем хранить.
def pdf_bytes(text: str) -> bytes:
    lines = text.split("\n")
    stream = "BT /F1 10 Tf 1 0 0 1 20 760 Tm 12 TL\n"
    for line in lines:
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
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n"
    )
    return out.encode("latin-1")


@pytest.fixture
def client():
    sessions.live.clear()
    with TestClient(app) as started:
        yield started


def upload(client, text=SAMPLE, name="transcript.pdf"):
    return client.post(
        "/transcript", files={"pdf": (name, pdf_bytes(text), "application/pdf")}
    )


def test_landing_asks_for_a_transcript(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Загрузите транскрипт" in response.text
    # Пока транскрипта нет, разделов в шапке тоже нет
    assert "/audit" not in response.text


def test_full_transcript_is_accepted_and_shown(client):
    assert upload(client).status_code == 200  # TestClient идёт по редиректу

    page = client.get("/student")
    assert "Test Student" in page.text
    assert "Computer Science" in page.text
    assert "SCAI" in page.text
    # Незачтённый курс виден, но кредитов не приносит
    assert "16 ECTS" in page.text
    assert "нет оценки" in page.text


def test_partial_transcript_is_refused(client):
    # Итоговая строка говорит о 198 кредитах, а курсов в файле на 16
    broken = SAMPLE.replace("Credits Earned: 16\n", "Credits Earned: 198\n")
    response = upload(client, broken)

    assert "Загрузите транскрипт целиком" in response.text
    assert "нашли по курсам" in response.text
    # Сессия не заведена: считать по такому файлу нельзя
    assert client.get("/student").url.path == "/"


def test_file_that_is_not_a_pdf_is_refused(client):
    response = client.post(
        "/transcript", files={"pdf": ("заметки.pdf", "не pdf вовсе".encode(), "application/pdf")}
    )
    assert "Не удалось прочитать транскрипт" in response.text


def test_pdf_without_courses_is_refused(client):
    response = upload(client, "NAZARBAYEV UNIVERSITY\nStudent Unofficial Transcript\n")
    assert "Не удалось прочитать транскрипт" in response.text


def test_student_page_needs_a_transcript(client):
    assert client.get("/student").url.path == "/"


def test_forgetting_removes_the_transcript(client):
    upload(client)
    assert client.get("/student").status_code == 200

    client.post("/forget")
    assert not sessions.live
    assert client.get("/student").url.path == "/"


def test_header_shows_who_is_working(client):
    upload(client)
    page = client.get("/student")
    assert "с Fall 2023" in page.text
    assert "GPA 3.0" in page.text


def test_sessions_forget_stale_ones():
    store = Sessions()
    key = store.start(parse_text(SAMPLE))
    assert store.get(key) is not None

    store.live[key].seen = store.live[key].seen.replace(year=2000)
    assert store.get(key) is None
    assert key not in store.live


def test_session_key_is_not_guessable():
    store = Sessions()
    keys = {store.start(parse_text(SAMPLE)) for _ in range(5)}
    assert len(keys) == 5
    assert all(len(key) > 20 for key in keys)
    assert COOKIE == "session"


def test_student_chip_leaves_out_what_is_missing():
    chip = view.student_chip(parse_text("Student Name: Кто-то\n"))
    assert chip["name"] == "Кто-то"
    # Ни специальности, ни года поступления в файле нет — и в шапке их нет
    assert "None" not in chip["facts"]


# --- аудит ---

def test_audit_needs_a_transcript(client):
    assert client.get("/audit").url.path == "/"


def test_term_of_counts_from_the_admission_semester():
    assert view.term_of("Fall 2023", 1) == "Fall 2023"
    assert view.term_of("Fall 2023", 2) == "Spring 2024"
    assert view.term_of("Fall 2023", 7) == "Fall 2026"
    assert view.term_of("Fall 2023", 8) == "Spring 2027"
    # Поступившим весной первый семестр — их весна
    assert view.term_of("Spring 2024", 1) == "Spring 2024"
    assert view.term_of("Spring 2024", 2) == "Fall 2024"
    assert view.term_of("", 1) == ""


# --- рекомендации ---

def test_courses_need_a_transcript(client):
    assert client.get("/courses").url.path == "/"
