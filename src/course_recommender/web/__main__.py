"""Запуск веб-интерфейса.

    uv run python -m course_recommender.web
"""

from __future__ import annotations


def main() -> None:
    import argparse
    import os

    import uvicorn

    # Хостинги сообщают адрес и порт через окружение, локально нужен localhost:
    # слушать все интерфейсы на своей машине незачем.
    parser = argparse.ArgumentParser(description="Запустить веб-интерфейс")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run(
        "course_recommender.web.app:app", host=args.host, port=args.port, reload=args.reload
    )


if __name__ == "__main__":
    main()
