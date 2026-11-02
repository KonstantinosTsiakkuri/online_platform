# LMS — онлайн-платформа (Django REST Framework)

Курсы, уроки, подписки, пользователи (JWT), оплата курсов через Stripe, фоновые задачи на Celery.

- Документация API: `http://127.0.0.1:8000/api/docs/` (Swagger), `/api/redoc/`, схема `/api/schema/`.
- Стек: Python 3.13, Django 6.0, DRF, SimpleJWT, drf-spectacular, Stripe, PostgreSQL, Celery + Redis, django-celery-beat.
- Запуск: локально (раздел «Установка») или целиком в Docker (раздел «Запуск через Docker»).

## Установка (без Docker)

Нужны Python 3.13, Poetry, PostgreSQL и Redis. Создайте базу данных, например:

```bash
psql -U postgres -c "CREATE DATABASE online_platform"
```


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
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | PostgreSQL. Те же имена читает образ `postgres` в Docker, поэтому один `.env` подходит и Django, и контейнеру БД. Без Docker `POSTGRES_HOST=localhost` |
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

## Запуск через Docker

Весь проект (база, Redis, сервер, worker и beat) поднимается одной командой.

### Требования
- Docker Desktop (Windows/macOS) или Docker Engine + плагин Compose (Linux); команды ниже — `docker compose`.

### Шаги

1. Создайте `.env` из шаблона и заполните его:
   ```bash
   copy .env.example .env      # Linux/macOS: cp .env.example .env
   ```
   Обязательно задайте `SECRET_KEY` и `POSTGRES_PASSWORD` (`POSTGRES_DB`, `POSTGRES_USER` можно оставить). Оставьте `DEBUG=True`
   (сервер разработки отдаёт статику Swagger и медиа только в этом режиме) и `ALLOWED_HOSTS=127.0.0.1,localhost`.
   Для почты и Stripe заполните `EMAIL_*` и `STRIPE_*` по желанию.
   `POSTGRES_HOST` и `REDIS_HOST` менять не нужно: в Docker compose сам подставляет `db` и `redis`.
2. Соберите образ и запустите все сервисы:
   ```bash
   docker compose up -d --build
   ```
   При старте `app` сам применяет миграции. Проверка состояния: `docker compose ps` (все сервисы `Up`, `db`, `redis` и `app` — `healthy`).
3. Создайте суперпользователя и группу модераторов:
   ```bash
   docker compose exec app python manage.py createsuperuser
   docker compose exec app python manage.py loaddata groups
   ```
4. Откройте в браузере: Swagger — http://localhost:8000/api/docs/, админка — http://localhost:8000/admin/.

База в контейнере `db` создаётся пустой и не связана с вашей локальной PostgreSQL. Тестовые данные можно загрузить
фикстурами: `docker compose exec app python manage.py loaddata materials_data users_data payments_data`.

### Управление

```bash
docker compose logs -f app            # логи одного сервиса (app, celery, celery_beat, db, redis)
docker compose logs -f celery celery_beat
docker compose stop                   # остановить, данные сохраняются
docker compose start                  # запустить снова
docker compose down                   # удалить контейнеры (тома с данными остаются)
```

Не используйте `docker compose down -v`, если не хотите удалить базу данных, данные Redis и загруженные файлы (именованные тома).
Выполнить любую команду Django: `docker compose exec app python manage.py <команда>`; тесты: `docker compose exec app python manage.py test`
(тесты Django нужны dev-зависимости, которых в образе нет, — для запуска тестов используйте локальное окружение).

### Сервисы

| Сервис | Образ | Назначение | Порт наружу | Данные (volume) |
|---|---|---|---|---|
| `db` | `postgres:17-alpine` | база данных PostgreSQL | нет (только `expose: 5432` внутри сети) | `pg_data` → `/var/lib/postgresql/data` |
| `redis` | `redis:7-alpine` | брокер и хранилище результатов Celery | нет (только `expose: 6379`) | `redis_data` → `/data` |
| `app` | сборка из `Dockerfile` | Django: миграции и `runserver 0.0.0.0:8000` | **8000:8000** | `media_data` → `/app/media` |
| `celery` | тот же образ | worker: выполняет фоновые задачи (рассылка писем) | нет | `media_data` → `/app/media` |
| `celery_beat` | тот же образ | планировщик периодических задач (`DatabaseScheduler`) | нет | — |

Порядок старта обеспечивают `healthcheck` и `depends_on: condition: service_healthy`: сначала `db` и `redis`, затем `app` (миграции), затем `celery` и `celery_beat`.

### Почему `db` и `redis` не проброшены наружу

Они объявлены через `expose`, а не `ports`: доступны только другим контейнерам по именам `db` и `redis` во внутренней сети compose.
Базе данных и Redis не нужен доступ из интернета и с остальных программ компьютера — меньше поверхность атаки, нет конфликта с локально
установленными PostgreSQL и Redis на тех же портах. Наружу торчит только `app` на порту 8000.
Если нужен доступ с вашего компьютера (например, из DBeaver), временно добавьте `ports: ["5433:5432"]` сервису `db`.

## Тесты и проверки

```bash
poetry run python manage.py test
poetry run coverage run manage.py test && poetry run coverage report
poetry run flake8 .
poetry run mypy .
poetry run python manage.py spectacular --validate --fail-on-warn
```

Тестам Redis и SMTP не нужны: Celery-задачи вызываются напрямую или мокаются, письма идут в `locmem`.
