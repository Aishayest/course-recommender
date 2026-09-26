"""Кто сейчас работает с системой.

Транскрипт — персональные данные, и на диск он не ложится: разобранное
живёт в памяти процесса, а браузеру достаётся только случайный ключ.
Закрыли приложение — не осталось ничего.

Такой способ рассчитан на один процесс: это инструмент, который студент
запускает у себя, а не сервис на много пользователей. Понадобится второе —
понадобится и настоящее хранилище.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..data.transcripts import Transcript

COOKIE = "session"
# Сколько сессия живёт без обращений.
LIFETIME_HOURS = 12


@dataclass
class Session:
    """Разобранный транскрипт одного студента."""

    transcript: Transcript
    created: datetime = field(default_factory=lambda: datetime.now(UTC))
    seen: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def age_hours(self) -> float:
        return (datetime.now(UTC) - self.seen).total_seconds() / 3600


@dataclass
class Sessions:
    """Все, кто сейчас работает."""

    live: dict[str, Session] = field(default_factory=dict)

    def start(self, transcript: Transcript) -> str:
        """Запомнить транскрипт и выдать ключ."""
        self.forget_stale()
        key = secrets.token_urlsafe(24)
        self.live[key] = Session(transcript=transcript)
        return key

    def get(self, key: str | None) -> Session | None:
        session = self.live.get(key) if key else None
        if session is None:
            return None
        if session.age_hours > LIFETIME_HOURS:
            self.live.pop(key, None)
            return None
        session.seen = datetime.now(UTC)
        return session

    def end(self, key: str | None) -> None:
        if key:
            self.live.pop(key, None)

    def forget_stale(self) -> None:
        for key, session in list(self.live.items()):
            if session.age_hours > LIFETIME_HOURS:
                self.live.pop(key, None)
