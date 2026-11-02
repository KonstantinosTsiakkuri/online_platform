"""Тесты рассылки об обновлении курса (Celery-задача и её вызов из контроллера)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from kombu.exceptions import OperationalError
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User

from .models import Course, Subscription
from .tasks import send_course_update_email

FAST_HASHER = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DELAY = "materials.views.send_course_update_email.delay"


@override_settings(PASSWORD_HASHERS=FAST_HASHER)
class CourseUpdateTestCase(APITestCase):
    """Общая подготовка: владелец и его курс, который последний раз обновлялся 5 часов назад."""

    def setUp(self) -> None:
        self.owner = User.objects.create_user(email="owner@test.com", password="x")
        self.course = Course.objects.create(title="Python", owner=self.owner)
        # курс последний раз обновлялся давно — письмо при обновлении должно уходить
        self.set_last_update(hours=5)
        self.url = reverse("materials:courses-detail", args=[self.course.pk])
        self.client.force_authenticate(user=self.owner)

    def set_last_update(self, **delta: float) -> None:
        # update() не вызывает save(), поэтому auto_now не перезапишет значение
        Course.objects.filter(pk=self.course.pk).update(updated_at=timezone.now() - timedelta(**delta))


class CourseUpdateTriggersEmailTests(CourseUpdateTestCase):
    @patch(DELAY)
    def test_patch_schedules_task_after_commit(self, delay: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.patch(self.url, {"title": "Python PRO"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # до фиксации транзакции задача не ставится
        delay.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        delay.assert_called_once_with(self.course.pk)

    @patch(DELAY)
    def test_put_schedules_task(self, delay: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.put(self.url, {"title": "Новое название"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        delay.assert_called_once_with(self.course.pk)
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Новое название")

    @patch(DELAY)
    def test_invalid_update_does_not_schedule_task(self, delay: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.patch(self.url, {"description": "https://evil.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(callbacks, [])
        delay.assert_not_called()

    @patch(DELAY)
    def test_create_and_delete_do_not_schedule_task(self, delay: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(reverse("materials:courses-list"), {"title": "Новый"}, format="json")
            self.client.delete(reverse("materials:courses-detail", args=[created.json()["id"]]))
        delay.assert_not_called()

    @patch(DELAY, side_effect=OperationalError("Redis недоступен"))
    def test_broker_failure_does_not_break_api(self, delay: MagicMock) -> None:
        with self.assertLogs("django", level="ERROR") as logs:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(self.url, {"title": "Без Redis"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        delay.assert_called_once_with(self.course.pk)
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Без Redis")
        self.assertIn("Redis недоступен", logs.output[0])


class FourHourLimitTests(CourseUpdateTestCase):
    """Письмо не отправляется, если курс уже обновлялся менее 4 часов назад."""

    def patch_course(self, title: str) -> None:
        response = self.client.patch(self.url, {"title": title}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(DELAY)
    def test_recent_update_does_not_send(self, delay: MagicMock) -> None:
        self.set_last_update(hours=3, minutes=59)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.patch_course("Обновлён недавно")
        self.assertEqual(callbacks, [])
        delay.assert_not_called()
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, "Обновлён недавно")  # само обновление при этом сохраняется

    @patch(DELAY)
    def test_update_after_four_hours_sends(self, delay: MagicMock) -> None:
        self.set_last_update(hours=4, minutes=1)
        with self.captureOnCommitCallbacks(execute=True):
            self.patch_course("Прошло больше 4 часов")
        delay.assert_called_once_with(self.course.pk)

    @patch(DELAY)
    def test_exactly_four_hours_sends(self, delay: MagicMock) -> None:
        self.set_last_update(hours=4)
        with self.captureOnCommitCallbacks(execute=True):
            self.patch_course("Ровно 4 часа")
        delay.assert_called_once_with(self.course.pk)

    @patch(DELAY)
    def test_second_update_in_a_row_does_not_send(self, delay: MagicMock) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            self.patch_course("Первое обновление")
            self.patch_course("Второе через секунду")
        delay.assert_called_once_with(self.course.pk)

    @patch(DELAY)
    def test_updated_at_is_refreshed_on_save(self, delay: MagicMock) -> None:
        before = Course.objects.get(pk=self.course.pk).updated_at
        with self.captureOnCommitCallbacks(execute=True):
            self.patch_course("Новое")
        after = Course.objects.get(pk=self.course.pk).updated_at
        self.assertGreater(after, before)
        self.assertLess(timezone.now() - after, timedelta(minutes=1))

    @patch(DELAY)
    def test_just_created_course_update_does_not_send(self, delay: MagicMock) -> None:
        created = self.client.post(reverse("materials:courses-list"), {"title": "Свежий"}, format="json").json()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(reverse("materials:courses-detail", args=[created["id"]]), {"title": "x"}, format="json")
        delay.assert_not_called()


@override_settings(PASSWORD_HASHERS=FAST_HASHER, DEFAULT_FROM_EMAIL="lms@test.com")
class SendCourseUpdateEmailTaskTests(TestCase):
    def setUp(self) -> None:
        self.course = Course.objects.create(title="Django")
        self.other_course = Course.objects.create(title="SQL")
        self.subscribers = [User.objects.create_user(email=f"sub{i}@test.com", password="x") for i in range(3)]
        for user in self.subscribers:
            Subscription.objects.create(user=user, course=self.course)
        stranger = User.objects.create_user(email="stranger@test.com", password="x")
        Subscription.objects.create(user=stranger, course=self.other_course)

    def test_sends_one_email_per_subscriber_of_this_course(self) -> None:
        sent = send_course_update_email(self.course.pk)
        self.assertEqual(sent, 3)
        self.assertEqual(len(mail.outbox), 3)
        recipients = sorted(message.to[0] for message in mail.outbox)
        self.assertEqual(recipients, ["sub0@test.com", "sub1@test.com", "sub2@test.com"])
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)  # адреса подписчиков не видны друг другу
            self.assertIn("Django", message.subject)
            self.assertIn("Django", message.body)
            self.assertEqual(message.from_email, "lms@test.com")
        self.assertNotIn("stranger@test.com", recipients)

    def test_emails_are_selected_in_one_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            send_course_update_email(self.course.pk)
        subscription_queries = [q for q in queries.captured_queries if "materials_subscription" in q["sql"]]
        self.assertEqual(len(subscription_queries), 1)
        self.assertEqual(len(queries.captured_queries), 2)  # курс + email подписчиков

    def test_inactive_subscriber_is_skipped(self) -> None:
        User.objects.filter(email="sub0@test.com").update(is_active=False)
        self.assertEqual(send_course_update_email(self.course.pk), 2)
        self.assertNotIn("sub0@test.com", [m.to[0] for m in mail.outbox])

    def test_no_subscribers(self) -> None:
        empty = Course.objects.create(title="Пустой")
        self.assertEqual(send_course_update_email(empty.pk), 0)
        self.assertEqual(mail.outbox, [])

    def test_unknown_course(self) -> None:
        self.assertEqual(send_course_update_email(99999), 0)
        self.assertEqual(mail.outbox, [])

    def test_task_is_registered_in_celery(self) -> None:
        from config import celery_app

        self.assertIn("materials.tasks.send_course_update_email", celery_app.tasks)
        self.assertEqual(send_course_update_email.name, "materials.tasks.send_course_update_email")
