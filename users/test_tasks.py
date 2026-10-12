"""Тесты блокировки неактивных пользователей и настроек Celery beat."""

from datetime import timedelta

from celery.schedules import crontab
from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import User
from .tasks import block_inactive_users

FAST_HASHER = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@override_settings(PASSWORD_HASHERS=FAST_HASHER)
class BlockInactiveUsersTests(TestCase):
    def setUp(self) -> None:
        now = timezone.now()
        self.inactive = self.make("inactive@test.com", last_login=now - timedelta(days=31))
        self.active = self.make("active@test.com", last_login=now - timedelta(days=1))
        self.almost = self.make("almost@test.com", last_login=now - timedelta(days=29, hours=23))
        self.superuser = User.objects.create_superuser(email="admin@test.com", password="x")
        User.objects.filter(pk=self.superuser.pk).update(last_login=now - timedelta(days=100))
        self.never = self.make("never@test.com", last_login=None)
        self.already_blocked = self.make("blocked@test.com", last_login=now - timedelta(days=60), is_active=False)

    def make(self, email: str, **fields: object) -> User:
        user = User.objects.create_user(email=email, password="x")
        User.objects.filter(pk=user.pk).update(**fields)
        user.refresh_from_db()
        return user

    def assert_active(self, user: User, expected: bool) -> None:
        user.refresh_from_db()
        self.assertEqual(user.is_active, expected, user.email)

    def test_blocks_only_users_inactive_for_30_days(self) -> None:
        blocked = block_inactive_users()
        self.assertEqual(blocked, 1)
        self.assert_active(self.inactive, False)
        self.assert_active(self.active, True)
        self.assert_active(self.almost, True)
        self.assert_active(self.superuser, True)
        self.assert_active(self.never, True)
        self.assert_active(self.already_blocked, False)

    def test_single_update_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            block_inactive_users()
        self.assertEqual(len(queries.captured_queries), 1)
        self.assertTrue(queries.captured_queries[0]["sql"].upper().startswith("UPDATE"))

    def test_second_run_blocks_nobody(self) -> None:
        block_inactive_users()
        self.assertEqual(block_inactive_users(), 0)

    def test_result_is_logged(self) -> None:
        with self.assertLogs("users.tasks", level="INFO") as logs:
            block_inactive_users()
        self.assertIn("1", logs.output[0])


@override_settings(PASSWORD_HASHERS=FAST_HASHER)
class LastLoginUpdateTests(APITestCase):
    def test_token_obtain_updates_last_login(self) -> None:
        user = User.objects.create_user(email="login@test.com", password="Str0ng-Pass!2026")
        self.assertIsNone(user.last_login)
        response = self.client.post(
            reverse("users:token-obtain"), {"email": "login@test.com", "password": "Str0ng-Pass!2026"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertIsNotNone(user.last_login)
        assert user.last_login is not None
        self.assertLess(timezone.now() - user.last_login, timedelta(minutes=1))


class CeleryConfigTests(TestCase):
    def test_beat_schedule_runs_block_daily(self) -> None:
        entry = settings.CELERY_BEAT_SCHEDULE["block-inactive-users"]
        self.assertEqual(entry["task"], "users.tasks.block_inactive_users")
        self.assertEqual(entry["schedule"], crontab(hour=3, minute=0))

    def test_celery_settings(self) -> None:
        from config import celery_app

        self.assertEqual(celery_app.conf.timezone, settings.TIME_ZONE)
        self.assertTrue(celery_app.conf.task_track_started)
        self.assertEqual(celery_app.conf.beat_scheduler, "django_celery_beat.schedulers:DatabaseScheduler")
        self.assertIn("users.tasks.block_inactive_users", celery_app.tasks)
        self.assertTrue(settings.SIMPLE_JWT["UPDATE_LAST_LOGIN"])
