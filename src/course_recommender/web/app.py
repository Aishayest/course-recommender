"""Веб-интерфейс.

Студент загружает транскрипт и получает ответ на три вопроса: что осталось
до диплома, что брать в следующем семестре и как это складывается в
расписание. Вся работа делается слоями ниже; здесь только маршруты и показ.

Разобранные источники читаются один раз при старте — командой prepare они
уже сложены в data/processed, и подниматься приложение должно за секунду,
а не за минуты разбора PDF.

    uv run python -m course_recommender.web
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..data import prepare
from ..data.transcripts import parse_stream
from . import service, view
from .state import COOKIE, Sessions

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
sessions = Sessions()
# Что удалось подготовить. Заполняется при старте.
data = prepare.Prepared()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Прочитать подготовленные данные при старте."""
    global data
    data = prepare.load()
    yield


app = FastAPI(title="Course Recommender", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


def current_term() -> str | None:
    """Семестр, на который советуем: последний известный каталогу."""
    terms = data.terms
    return terms[-1] if terms else None


def page(request: Request, template: str, **context) -> HTMLResponse:
    """Отрисовать страницу с общим окружением шапки."""
    session = sessions.get(request.cookies.get(COOKIE))
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "student": view.student_chip(session.transcript) if session else None,
            "term": current_term(),
            "sections": view.SECTIONS,
            **context,
        },
    )


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request) -> HTMLResponse:
    """Загрузка транскрипта — с неё начинается всё остальное."""
    return page(request, "upload.html", error=None, active=None)


@app.post("/transcript")
async def receive_transcript(
    request: Request, pdf: Annotated[UploadFile, File()]
) -> HTMLResponse:
    """Разобрать загруженный транскрипт.

    Неполный файл отклоняется: по половине выгрузки аудит соврёт, а молчать
    об этом хуже, чем отказаться считать.
    """
    from io import BytesIO

    from pdfplumber.utils.exceptions import PdfminerException

    name = pdf.filename or "транскрипт.pdf"
    try:
        transcript = parse_stream(BytesIO(await pdf.read()))
    except (PdfminerException, ValueError, OSError):
        # Прислали не PDF, повреждённый файл или картинку вместо текста.
        return page(request, "upload.html", error=view.unreadable_error(name), active=None)

    if not transcript.courses:
        return page(request, "upload.html", error=view.unreadable_error(name), active=None)
    if transcript.is_partial:
        return page(
            request,
            "upload.html",
            error=view.partial_transcript_error(name, transcript),
            active=None,
        )

    key = sessions.start(transcript)
    response = RedirectResponse(url="/student", status_code=303)
    response.set_cookie(COOKIE, key, httponly=True, samesite="lax")
    return response


@app.get("/student", response_class=HTMLResponse)
def student_page(request: Request) -> HTMLResponse:
    """Что разобрали из транскрипта."""
    session = sessions.get(request.cookies.get(COOKIE))
    if session is None:
        return RedirectResponse(url="/", status_code=303)
    return page(
        request,
        "student.html",
        summary=view.transcript_summary(session.transcript),
        active=None,
    )


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request) -> HTMLResponse:
    """Что студенту осталось до диплома."""
    session = sessions.get(request.cookies.get(COOKIE))
    if session is None:
        return RedirectResponse(url="/", status_code=303)

    found = service.audit_of(session.transcript, data, current_term())
    if found is None:
        return page(
            request,
            "unknown_program.html",
            major=session.transcript.major,
            year=session.transcript.admission_year,
            active="audit",
        )

    _, result = found
    return page(
        request,
        "audit.html",
        audit=view.audit_page(result, session.transcript),
        active="audit",
    )


@app.post("/forget")
def forget(request: Request) -> RedirectResponse:
    """Убрать транскрипт из памяти."""
    sessions.end(request.cookies.get(COOKIE))
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(COOKIE)
    return response
