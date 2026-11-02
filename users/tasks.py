import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from .models import User

logger = logging.getLogger(__name__)

INACTIVITY_DAYS = 30


@shared_task
def block_inactive_users() -> int:
    """Блокирует (is_active=False) пользователей, которые не входили больше 30 дней. Возвращает их число.

    Суперпользователи не блокируются. Пользователи с last_login = NULL (ни разу не входили) не трогаются.
    """
    threshold = timezone.now() - timedelta(days=INACTIVITY_DAYS)
    blocked = (
        User.objects.filter(is_active=True, last_login__lt=threshold)
        .exclude(is_superuser=True)
        .update(is_active=False)
    )
    logger.info("Заблокировано неактивных пользователей: %s", blocked)
    return blocked
