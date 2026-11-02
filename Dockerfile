FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Poetry ставим в системный Python и отключаем виртуальные окружения: образ и так изолирован
RUN pip install "poetry==2.4.3" \
    && poetry config virtualenvs.create false

# Сначала только файлы зависимостей: пока они не менялись, слой с установкой берётся из кэша
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --only main --no-interaction --no-ansi

# Потом код проекта
COPY . .

# Запуск не от root. Каталоги media и staticfiles принадлежат этому пользователю:
# именованные volumes при первом подключении наследуют владельца каталога из образа
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/staticfiles \
    && chown -R app:app /app/media /app/staticfiles
USER app

EXPOSE 8000

# Боевой сервер. Полная команда запуска (migrate, collectstatic, gunicorn) задаётся в docker-compose.yaml
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
