# LMS — онлайн-платформа (Django REST Framework)

Курсы, уроки, подписки, пользователи (JWT), оплата курсов через Stripe, фоновые задачи на Celery.

- Приложение на сервере: **http://84.54.57.75/** (Swagger — http://84.54.57.75/api/docs/).
- Документация API: `/api/docs/` (Swagger), `/api/redoc/`, схема `/api/schema/` (локально без Docker — `http://127.0.0.1:8000/...`).
- Стек: Python 3.13, Django 6.0, DRF, SimpleJWT, drf-spectacular, Stripe, PostgreSQL, Celery + Redis, django-celery-beat.
- Запуск: локально (раздел «Установка»), в Docker (раздел «Запуск через Docker») или на сервере (разделы «Деплой на сервер» и «CI/CD»).

## Установка (без Docker)

Нужны Python 3.13, Poetry, PostgreSQL и Redis. Создайте базу данных, например:

```bash
psql -U postgres -c "CREATE DATABASE online_platform"
```


```bash
poetry install
copy .env.template .env     # Linux/macOS: cp .env.template .env — затем заполните значения
poetry run python manage.py migrate
poetry run python manage.py loaddata groups            # группа moderators
poetry run python manage.py createsuperuser
poetry run python manage.py runserver
```

## Переменные окружения (.env)

| Переменная | Назначение |
|---|---|
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | базовые настройки Django. В продакшене `DEBUG=False`, `ALLOWED_HOSTS=84.54.57.75`, `CSRF_TRUSTED_ORIGINS=http://84.54.57.75` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | PostgreSQL. Те же имена читает образ `postgres` в Docker, поэтому один `.env` подходит и Django, и контейнеру БД. Без Docker `POSTGRES_HOST=localhost` |
| `STRIPE_SECRET_KEY`, `STRIPE_CURRENCY`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | оплата через Stripe |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | Redis для Celery (брокер и результаты): `redis://REDIS_HOST:REDIS_PORT/REDIS_DB` |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | необязательно: полный адрес вместо трёх переменных выше |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | SMTP для писем. Если `EMAIL_HOST` пустой, письма печатаются в консоль worker'а |

Шаблон со всеми переменными и комментариями — `.env.template`.

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

Весь проект (nginx, Django на gunicorn, база, Redis, worker и beat) поднимается одной командой.

### Требования
- Docker Desktop (Windows/macOS) или Docker Engine + плагин Compose (Linux); команды ниже — `docker compose`.

### Шаги

1. Создайте `.env` из шаблона и заполните его:
   ```bash
   copy .env.template .env      # Linux/macOS: cp .env.template .env
   ```
   Обязательно задайте `SECRET_KEY` и `POSTGRES_PASSWORD` (`POSTGRES_DB`, `POSTGRES_USER` можно оставить).
   Для локального запуска `DEBUG=True`, `ALLOWED_HOSTS=127.0.0.1,localhost`, `CSRF_TRUSTED_ORIGINS=http://localhost,http://127.0.0.1`.
   Для почты и Stripe заполните `EMAIL_*` и `STRIPE_*` по желанию.
   `POSTGRES_HOST` и `REDIS_HOST` менять не нужно: в Docker compose сам подставляет `db` и `redis`.
2. Соберите образ и запустите все сервисы:
   ```bash
   docker compose up -d --build
   ```
   При старте `app` сам применяет миграции и собирает статику (`collectstatic`). Проверка состояния: `docker compose ps`
   (все сервисы `Up`, `db`, `redis` и `app` — `healthy`).
3. Создайте суперпользователя и группу модераторов:
   ```bash
   docker compose exec app python manage.py createsuperuser
   docker compose exec app python manage.py loaddata groups
   ```
4. Откройте в браузере: Swagger — http://localhost/api/docs/, админка — http://localhost/admin/ (порт 80, через nginx).

База в контейнере `db` создаётся пустой и не связана с вашей локальной PostgreSQL. Тестовые данные можно загрузить
фикстурами: `docker compose exec app python manage.py loaddata materials_data users_data payments_data`.

### Управление

```bash
docker compose logs -f app            # логи одного сервиса (app, nginx, celery, celery_beat, db, redis)
docker compose logs -f celery celery_beat
docker compose stop                   # остановить, данные сохраняются
docker compose start                  # запустить снова
docker compose down                   # удалить контейнеры (тома с данными остаются)
```

Не используйте `docker compose down -v`, если не хотите удалить базу данных, данные Redis и загруженные файлы (именованные тома).
Выполнить любую команду Django: `docker compose exec app python manage.py <команда>`; тесты Django нужны dev-зависимости, которых в образе
нет, — для запуска тестов используйте локальное окружение.

### Сервисы

| Сервис | Образ | Назначение | Порт наружу | Данные (volume) |
|---|---|---|---|---|
| `nginx` | `nginx:alpine` | веб-сервер: проксирует запросы на `app`, сам отдаёт `/static/` и `/media/` | **80:80** (единственный) | `static_data`, `media_data` (только чтение), конфиг `nginx/nginx.conf` |
| `app` | `ghcr.io/konstantinostsiakkuri/online_platform` (локально собирается из `Dockerfile`) | Django на gunicorn (2 воркера): миграции, `collectstatic`, `gunicorn config.wsgi:application` | нет (только `expose: 8000`) | `media_data` → `/app/media`, `static_data` → `/app/staticfiles` |
| `db` | `postgres:17-alpine` | база данных PostgreSQL | нет (только `expose: 5432`) | `pg_data` → `/var/lib/postgresql/data` |
| `redis` | `redis:7-alpine` | брокер и хранилище результатов Celery | нет (только `expose: 6379`) | `redis_data` → `/data` |
| `celery` | тот же образ, что `app` | worker: выполняет фоновые задачи (рассылка писем) | нет | `media_data` → `/app/media` |
| `celery_beat` | тот же образ, что `app` | планировщик периодических задач (`DatabaseScheduler`) | нет | — |

Порядок старта обеспечивают `healthcheck` и `depends_on: condition: service_healthy`: сначала `db` и `redis`, затем `app` (миграции и статика),
затем `nginx`, `celery` и `celery_beat`. У всех сервисов `restart: unless-stopped`: после перезагрузки сервера они поднимутся сами.

### Почему наружу открыт только nginx

`db`, `redis` и `app` объявлены через `expose`, а не `ports`: они доступны только другим контейнерам по именам `db`, `redis`, `app`
во внутренней сети compose. Базе данных, Redis и gunicorn не нужен доступ из интернета — меньше поверхность атаки, нет конфликта с
локально установленными PostgreSQL и Redis на тех же портах. Единственная точка входа — nginx на порту 80.
Если нужен доступ к базе с вашего компьютера (например, из DBeaver), временно добавьте `ports: ["5433:5432"]` сервису `db`.

## Деплой на сервер

Приложение работает на сервере **84.54.57.75** (Ubuntu 24.04, Cloud.ru) по адресу **http://84.54.57.75/** (домена нет, доступ по IP, без HTTPS).
Образы Docker на сервере **не собираются** (слабая виртуальная машина): их собирает GitHub Actions и публикует в `ghcr.io`, сервер только скачивает готовый образ.

### Подготовка сервера (выполняется один раз)

1. Обновление пакетов, установка Docker Engine и плагина Compose из официального репозитория Docker, автозапуск службы `docker`;
   пользователь `deploy` добавлен в группу `docker`.
2. Файрвол `ufw`: разрешены только OpenSSH (22), 80 и 443 (порядок: сначала SSH, потом остальное, потом включение). Порты 5432, 6379 и 8000 снаружи закрыты:
   Docker их не публикует (в compose у `db`, `redis`, `app` только `expose`).
3. SSH: вход только по ключам (`PasswordAuthentication no`, `PermitRootLogin no`); учтены переопределения в `/etc/ssh/sshd_config.d/`.
4. Swap-файл 2 ГБ (`/swapfile`, прописан в `/etc/fstab`) — на ВМ с 4 ГБ RAM он защищает от нехватки памяти при запуске всех сервисов.
5. Отдельный ключ ed25519 для GitHub Actions: публичная часть в `~/.ssh/authorized_keys` пользователя `deploy`, приватная — в секрете `SSH_KEY`.
6. Каталог приложения `~/online_platform`. Файл `.env` на сервере вручную не создаётся: его записывает workflow из секретов.

### Что делает деплой

При каждом push GitHub Actions (job `deploy`):
1. копирует на сервер только `docker-compose.yaml` и `nginx/` (код уже внутри образа);
2. собирает файл `.env` из секретов репозитория и кладёт его на сервер с правами `600`;
3. входит в `ghcr.io` (секрет `GHCR_TOKEN`), выполняет `docker compose pull` и `docker compose up -d`, ждёт, пока сервисы станут здоровыми,
   выводит `docker compose ps`;
4. проверяет, что `http://84.54.57.75/api/schema/` отвечает 200.

Состояние на сервере: `ssh deploy@84.54.57.75 "cd ~/online_platform && docker compose ps"`. Логи: `docker compose logs -f app` (из того же каталога).
Первичная настройка после первого деплоя: `docker compose exec app python manage.py createsuperuser` и `loaddata groups` (см. раздел про Docker).

## CI/CD

Файл `.github/workflows/ci-cd.yml`. Триггеры: **push** (любая ветка) и **pull_request**. Этапы идут строго по цепочке, падение любого останавливает следующие:

| Этап | Что делает | Когда |
|---|---|---|
| `test` | Python 3.13, кэш зависимостей, service-контейнер PostgreSQL с healthcheck, `manage.py test` | push и pull_request |
| `lint` | `flake8` по конфигу `.flake8` | push и pull_request |
| `build` | сборка образа Docker; публикация в `ghcr.io/konstantinostsiakkuri/online_platform` с тегами `latest` и `<sha коммита>` | сборка — всегда; **публикация только при push** |
| `deploy` | копирование `docker-compose.yaml` и `nginx/` на сервер, запись `.env` из секретов, `docker compose pull` и `up -d` | **только при push** |

Внимание: деплой запускается при push в **любую** ветку, поэтому образ `latest` и сервер обновляются с последнего запушенного коммита.

## GitHub Secrets

Settings → Secrets and variables → Actions → New repository secret. В репозитории и workflow секретов в открытом виде нет.

| Секрет | Обязателен | Назначение |
|---|---|---|
| `SSH_KEY` | да | приватный ключ для входа на сервер (файл `github_actions_deploy`, целиком, вместе со строками `BEGIN`/`END`) |
| `SERVER_HOST` | да | адрес сервера: `84.54.57.75` |
| `SERVER_USER` | да | пользователь на сервере: `deploy` |
| `GHCR_TOKEN` | да | персональный токен GitHub (classic) с правом `read:packages`: сервер им скачивает образ из ghcr.io |
| `SECRET_KEY` | да | секретный ключ Django (длинная случайная строка) |
| `POSTGRES_DB`, `POSTGRES_USER` | да | имя базы и пользователь PostgreSQL |
| `POSTGRES_PASSWORD` | да | пароль PostgreSQL (используется и в тестах CI, и на сервере) |
| `ALLOWED_HOSTS` | да | `84.54.57.75` |
| `CSRF_TRUSTED_ORIGINS` | да | `http://84.54.57.75` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_SSL`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | нет | SMTP для рассылки писем; без `EMAIL_HOST` письма печатаются в лог worker'а |
| `STRIPE_SECRET_KEY`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | нет | оплата через Stripe |

`DEBUG=False`, `POSTGRES_HOST=db`, `REDIS_*` workflow записывает в `.env` сам. Шаблон всех переменных — `.env.template`.

## Тесты и проверки

```bash
poetry run python manage.py test
poetry run coverage run manage.py test && poetry run coverage report
poetry run flake8 .
poetry run mypy .
poetry run python manage.py spectacular --validate --fail-on-warn
```

Тестам Redis и SMTP не нужны: Celery-задачи вызываются напрямую или мокаются, письма идут в `locmem`.
