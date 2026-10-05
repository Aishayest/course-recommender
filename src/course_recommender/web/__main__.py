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
    parser = argparse.ArgumentParser(description="Run the web interface")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    # За прокси хостинга приложение видит http, хотя наружу отдаётся https.
    # Без доверия к X-Forwarded-Proto url_for построит ссылки на статику с
    # http, и браузер вырежет их как mixed content: страница останется без
    # стилей. Локально доверять некому, поэтому список берётся из окружения.
    uvicorn.run(
        "course_recommender.web.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
