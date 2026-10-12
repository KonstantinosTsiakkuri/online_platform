import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
# Все настройки Celery берутся из settings.py с префиксом CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")
# Ищет tasks.py во всех приложениях из INSTALLED_APPS
app.autodiscover_tasks()
