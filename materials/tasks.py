import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import get_connection, send_mail

from .models import Course, Subscription

logger = logging.getLogger(__name__)


@shared_task
def send_course_update_email(course_id: int) -> int:
    """Рассылает подписчикам курса письмо об его обновлении. Возвращает число отправленных писем."""
    course = Course.objects.filter(pk=course_id).only("id", "title").first()
    if course is None:
        logger.warning("Курс id=%s не найден, рассылка не выполнена", course_id)
        return 0

    # email всех активных подписчиков именно этого курса — одним запросом
    emails = list(
        Subscription.objects.filter(course_id=course_id, user__is_active=True).values_list("user__email", flat=True)
    )
    if not emails:
        logger.info("У курса id=%s нет подписчиков, письма не отправлялись", course_id)
        return 0

    subject = f"Курс «{course.title}» обновлён"
    message = (
        f"Здравствуйте!\n\nВ курсе «{course.title}», на который вы подписаны, появились обновления. "
        "Загляните на платформу, чтобы посмотреть новые материалы."
    )
    # Каждому подписчику отдельное письмо (адреса не видны друг другу), но через одно SMTP-соединение
    with get_connection() as connection:
        sent = sum(
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], connection=connection)
            for email in emails
        )
    logger.info("Курс id=%s: отправлено писем — %s", course_id, sent)
    return sent
