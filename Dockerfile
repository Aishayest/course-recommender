# Образ для бесплатных хостингов: Render, Hugging Face Spaces, Fly, Koyeb.
#
# Данные внутрь копируются готовыми — разбор двух десятков PDF занимает минуты
# и требует исходников, которых в репозитории нет. Собирать их надо локально
# командой prepare, а сюда кладётся уже разобранное.
FROM python:3.12-slim

WORKDIR /app

# Зависимости ставятся отдельным слоем: они меняются реже кода.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

# Выгрузка handbook и подготовленные кеши.
COPY data ./data

ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000

CMD ["python", "-m", "course_recommender.web"]
