# LMS — онлайн-платформа (Django REST Framework)

Курсы, уроки, подписки, пользователи (JWT), оплата курсов через Stripe, фоновые задачи на Celery.

- Документация API: `http://127.0.0.1:8000/api/docs/` (Swagger), `/api/redoc/`, схема `/api/schema/`.
- Стек: Python 3.13, Django 6.0, DRF, SimpleJWT, drf-spectacular, Stripe, Celery + Redis, django-celery-beat.

## Установка

```bash
poetry install
copy .env.example .env      # Linux/macOS: cp .env.example .env — затем заполните значения
poetry run python manage.py migrate
poetry run python manage.py loaddata groups            # группа moderators
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

## Переменные окружения (.env)

| Переменная | Назначение |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | базовые настройки Django |
| `STRIPE_SECRET_KEY`, `STRIPE_CURRENCY`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | оплата через Stripe |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | Redis для Celery (брокер и результаты): `redis://REDIS_HOST:REDIS_PORT/REDIS_DB` |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | необязательно: полный адрес вместо трёх переменных выше |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | SMTP для писем. Если `EMAIL_HOST` пустой, письма печатаются в консоль worker'а |

Шаблон со всеми переменными — `.env.example`.

## Фоновые задачи (Celery)

| Задача | Когда выполняется |
|---|---|
| `materials.tasks.send_course_update_email` | после успешного обновления курса (PUT/PATCH `/courses/{id}/`) — письмо всем подписчикам курса; не отправляется, если курс уже обновлялся менее 4 часов назад |
| `users.tasks.block_inactive_users` | по расписанию celery-beat раз в сутки в 03:00 (Europe/Moscow) — блокирует пользователей, не входивших больше 30 дней (кроме суперпользователей) |

### 1. Запустить Redis

Redis должен слушать `localhost:6379` (или адрес из `.env`). Варианты для Windows:

- **WSL (Ubuntu):** `sudo apt install redis-server`, затем `sudo service redis-server start`;
- **Docker Desktop:** `docker run -d --name redis -p 6379:6379 redis:7`;
- **Memurai** (Redis-совместимый сервер для Windows): установить с memurai.com, служба запускается автоматически.

Проверка: `redis-cli ping` → `PONG`.

Подойдёт и старый Redis 3.x для Windows: Python-библиотека `redis` в проекте ограничена `<6.5` (этого требует kombu), она работает по протоколу RESP2, который понимает Redis 3.
### 2. Запустить worker и beat

В двух отдельных терминалах из корня проекта (рядом должен работать `runserver`):

```bash
# worker: на Windows обязательно пул solo
poetry run celery -A config worker -l INFO -P solo

# beat: планировщик периодических задач (расписание хранится в БД, django-celery-beat)
poetry run celery -A config beat -l INFO
```

Расписание можно смотреть и менять в админке: `/admin/` → Periodic Tasks.

## Тесты и проверки

```bash
poetry run python manage.py test
poetry run coverage run manage.py test && poetry run coverage report
poetry run flake8 .
poetry run mypy .
poetry run python manage.py spectacular --validate --fail-on-warn
```

Тестам Redis и SMTP не нужны: Celery-задачи вызываются напрямую или мокаются, письма идут в `locmem`.
