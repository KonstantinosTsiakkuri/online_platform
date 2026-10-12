from typing import Any

from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from users.models import User

from .models import Course, Lesson, Subscription
from .validators import is_allowed_host

VALID_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])  # быстрее в тестах
class BaseMaterialsTestCase(APITestCase):
    """Общие данные: владелец, модератор, посторонний пользователь, курс и урок владельца."""

    def setUp(self) -> None:
        self.owner = User.objects.create_user(email="owner@test.com", password="Str0ng-Pass!2026")
        self.moder = User.objects.create_user(email="moder@test.com", password="Str0ng-Pass!2026")
        self.outsider = User.objects.create_user(email="outsider@test.com", password="Str0ng-Pass!2026")
        group, _ = Group.objects.get_or_create(name="moderators")
        self.moder.groups.add(group)

        self.course = Course.objects.create(title="Курс владельца", description="Описание", owner=self.owner)
        self.lesson = Lesson.objects.create(
            title="Урок владельца",
            description="Текст",
            video_url=VALID_VIDEO,
            course=self.course,
            owner=self.owner,
        )

    def lesson_payload(self, **extra: Any) -> dict[str, Any]:
        data: dict[str, Any] = {"title": "Новый урок", "video_url": VALID_VIDEO, "course": self.course.pk}
        data.update(extra)
        return data


class LessonOwnerTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.owner)

    def test_create(self) -> None:
        response = self.client.post(reverse("materials:lesson-create"), self.lesson_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["owner"], self.owner.pk)
        self.assertEqual(Lesson.objects.count(), 2)
        self.assertTrue(Lesson.objects.filter(title="Новый урок", owner=self.owner).exists())

    def test_create_ignores_owner_from_body(self) -> None:
        payload = self.lesson_payload(owner=self.outsider.pk)
        response = self.client.post(reverse("materials:lesson-create"), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["owner"], self.owner.pk)

    def test_list(self) -> None:
        response = self.client.get(reverse("materials:lesson-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], self.lesson.pk)
        self.assertEqual(response.json()["results"][0]["title"], "Урок владельца")

    def test_retrieve(self) -> None:
        response = self.client.get(reverse("materials:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["video_url"], VALID_VIDEO)

    def test_update_put(self) -> None:
        payload = self.lesson_payload(title="Переименован")
        response = self.client.put(reverse("materials:lesson-update", args=[self.lesson.pk]), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.title, "Переименован")

    def test_update_patch(self) -> None:
        response = self.client.patch(
            reverse("materials:lesson-update", args=[self.lesson.pk]), {"description": "Новое"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.description, "Новое")
        self.assertEqual(self.lesson.title, "Урок владельца")

    def test_delete(self) -> None:
        response = self.client.delete(reverse("materials:lesson-delete", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Lesson.objects.count(), 0)


class LessonModeratorTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.moder)

    def test_list_sees_all(self) -> None:
        response = self.client.get(reverse("materials:lesson-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_retrieve(self) -> None:
        response = self.client.get(reverse("materials:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_update_patch_and_put(self) -> None:
        url = reverse("materials:lesson-update", args=[self.lesson.pk])
        response = self.client.patch(url, {"description": "Правка модератора"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.put(url, self.lesson_payload(title="Заголовок модератора"), format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.title, "Заголовок модератора")
        self.assertEqual(self.lesson.owner, self.owner)

    def test_create_forbidden(self) -> None:
        response = self.client.post(reverse("materials:lesson-create"), self.lesson_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Lesson.objects.count(), 1)

    def test_delete_forbidden(self) -> None:
        response = self.client.delete(reverse("materials:lesson-delete", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Lesson.objects.filter(pk=self.lesson.pk).exists())


class LessonOutsiderTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.outsider)

    def test_list_has_no_foreign_lessons(self) -> None:
        response = self.client.get(reverse("materials:lesson-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(response.json()["results"], [])

    def test_retrieve_foreign_is_hidden(self) -> None:
        response = self.client.get(reverse("materials:lesson-detail", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_update_foreign_is_hidden(self) -> None:
        url = reverse("materials:lesson-update", args=[self.lesson.pk])
        response = self.client.patch(url, {"title": "Взлом"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.title, "Урок владельца")

    def test_delete_foreign_is_hidden(self) -> None:
        response = self.client.delete(reverse("materials:lesson-delete", args=[self.lesson.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Lesson.objects.count(), 1)

    def test_can_create_own_lesson(self) -> None:
        response = self.client.post(reverse("materials:lesson-create"), self.lesson_payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["owner"], self.outsider.pk)


class LessonAnonymousTests(BaseMaterialsTestCase):
    def test_all_endpoints_require_auth(self) -> None:
        pk = self.lesson.pk
        requests = [
            self.client.get(reverse("materials:lesson-list")),
            self.client.post(reverse("materials:lesson-create"), self.lesson_payload(), format="json"),
            self.client.get(reverse("materials:lesson-detail", args=[pk])),
            self.client.patch(reverse("materials:lesson-update", args=[pk]), {"title": "x"}, format="json"),
            self.client.delete(reverse("materials:lesson-delete", args=[pk])),
        ]
        for response in requests:
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Lesson.objects.count(), 1)
        self.assertEqual(Lesson.objects.get(pk=pk).title, "Урок владельца")


class LinkValidationTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.owner)
        self.create_url = reverse("materials:lesson-create")
        self.update_url = reverse("materials:lesson-update", args=[self.lesson.pk])

    def test_create_with_foreign_link_rejected(self) -> None:
        response = self.client.post(
            self.create_url, self.lesson_payload(video_url="https://vimeo.com/12345"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        message = response.json()["video_url"][0]
        self.assertIn("youtube.com", message)
        self.assertIn("https://vimeo.com/12345", message)
        self.assertIn("Ссылка на видео", message)
        self.assertEqual(Lesson.objects.count(), 1)

    def test_update_with_foreign_link_rejected(self) -> None:
        response = self.client.patch(self.update_url, {"video_url": "https://rutube.ru/video/1/"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("video_url", response.json())
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.video_url, VALID_VIDEO)

    def test_put_with_foreign_link_rejected(self) -> None:
        payload = self.lesson_payload(video_url="https://example.com/v")
        response = self.client.put(self.update_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_youtube_links_accepted(self) -> None:
        for url in (
            VALID_VIDEO,
            "https://youtube.com/watch?v=abc",
            "https://m.youtube.com/watch?v=abc",
            "http://www.youtube.com/embed/abc",
        ):
            response = self.client.post(self.create_url, self.lesson_payload(video_url=url), format="json")
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, url)

    def test_bypass_attempts_rejected(self) -> None:
        for url in (
            "https://youtube.com.evil.com/watch?v=1",
            "https://evil.com/youtube.com",
            "https://notyoutube.com/watch",
            "https://evil.com/?u=youtube.com",
            "https://youtube.com@evil.com/",
        ):
            response = self.client.post(self.create_url, self.lesson_payload(video_url=url), format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, url)
            self.assertIn("video_url", response.json(), url)
        self.assertEqual(Lesson.objects.count(), 1)

    def test_description_links_are_checked(self) -> None:
        bad = self.client.post(
            self.create_url,
            self.lesson_payload(description="Смотри тут: www.evil.com/video и ещё https://youtube.com/watch?v=1"),
            format="json",
        )
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", bad.json())
        self.assertIn("www.evil.com/video", bad.json()["description"][0])
        good = self.client.post(
            self.create_url,
            self.lesson_payload(description="Видео: www.youtube.com/watch?v=1, конспект ниже."),
            format="json",
        )
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)

    def test_text_without_links_and_empty_values_pass(self) -> None:
        response = self.client.post(
            self.create_url,
            {"title": "Без ссылок", "description": "Просто текст", "course": self.course.pk},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.client.patch(self.update_url, {"video_url": "", "description": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_patch_without_link_fields_passes(self) -> None:
        response = self.client.patch(self.update_url, {"title": "Другое название"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_course_description_is_checked(self) -> None:
        url = reverse("materials:courses-list")
        bad = self.client.post(url, {"title": "Курс", "description": "https://evil.com/x"}, format="json")
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("description", bad.json())
        good = self.client.post(url, {"title": "Курс", "description": "https://youtube.com/c/x"}, format="json")
        self.assertEqual(good.status_code, status.HTTP_201_CREATED)
        patch = self.client.patch(
            reverse("materials:courses-detail", args=[self.course.pk]), {"title": "Новое имя"}, format="json"
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)

    def test_is_allowed_host_helper(self) -> None:
        self.assertTrue(is_allowed_host("www.youtube.com/watch"))
        self.assertTrue(is_allowed_host("YOUTUBE.COM/x"))
        self.assertFalse(is_allowed_host("www.evil.com"))
        self.assertFalse(is_allowed_host("http://"))
        self.assertFalse(is_allowed_host("http://[invalid"))


class SubscriptionTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.url = reverse("materials:course-subscribe")
        self.client.force_authenticate(user=self.outsider)

    def test_url_does_not_clash_with_router(self) -> None:
        self.assertEqual(self.url, "/courses/subscribe/")

    def test_subscribe_then_unsubscribe(self) -> None:
        first = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json(), {"message": "Подписка добавлена"})
        self.assertTrue(Subscription.objects.filter(user=self.outsider, course=self.course).exists())

        second = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.json(), {"message": "Подписка удалена"})
        self.assertFalse(Subscription.objects.filter(user=self.outsider, course=self.course).exists())

    def test_missing_course_id(self) -> None:
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("course_id", response.json())

    def test_unknown_course(self) -> None:
        response = self.client.post(self.url, {"course_id": 99999}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_non_numeric_course_id(self) -> None:
        response = self.client.post(self.url, {"course_id": "abc"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous(self) -> None:
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(Subscription.objects.count(), 0)

    def test_subscriptions_are_per_user(self) -> None:
        Subscription.objects.create(user=self.owner, course=self.course)
        response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Subscription.objects.filter(course=self.course).count(), 2)

    def test_is_subscribed_flag_in_course(self) -> None:
        self.client.force_authenticate(user=self.owner)
        detail = reverse("materials:courses-detail", args=[self.course.pk])
        self.assertFalse(self.client.get(detail).json()["is_subscribed"])
        self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertTrue(self.client.get(detail).json()["is_subscribed"])
        listing = self.client.get(reverse("materials:courses-list")).json()["results"]
        self.assertTrue(listing[0]["is_subscribed"])
        self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertFalse(self.client.get(detail).json()["is_subscribed"])

    def test_is_subscribed_is_per_user(self) -> None:
        Subscription.objects.create(user=self.owner, course=self.course)
        self.client.force_authenticate(user=self.moder)
        detail = reverse("materials:courses-detail", args=[self.course.pk])
        self.assertFalse(self.client.get(detail).json()["is_subscribed"])

    def test_is_subscribed_without_request_or_anonymous(self) -> None:
        from django.contrib.auth.models import AnonymousUser
        from rest_framework.test import APIRequestFactory

        from .serializers import CourseSerializer

        self.assertFalse(CourseSerializer(self.course).data["is_subscribed"])
        request = APIRequestFactory().get("/")
        request.user = AnonymousUser()
        self.assertFalse(CourseSerializer(self.course, context={"request": request}).data["is_subscribed"])

    def test_subscription_str_and_unique_constraint(self) -> None:
        subscription = Subscription.objects.create(user=self.owner, course=self.course)
        self.assertIn("owner@test.com", str(subscription))
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            Subscription.objects.create(user=self.owner, course=self.course)


class PaginationTests(BaseMaterialsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(user=self.owner)

    def make_lessons(self, count: int) -> None:
        Lesson.objects.bulk_create(
            [Lesson(title=f"Урок {i}", course=self.course, owner=self.owner) for i in range(count)]
        )

    def make_courses(self, count: int) -> None:
        Course.objects.bulk_create([Course(title=f"Курс {i}", owner=self.owner) for i in range(count)])

    def test_response_structure(self) -> None:
        for url in (reverse("materials:lesson-list"), reverse("materials:courses-list")):
            body = self.client.get(url).json()
            self.assertEqual(set(body), {"count", "next", "previous", "results"})
            self.assertEqual(body["count"], 1)
            self.assertIsNone(body["next"])
            self.assertIsNone(body["previous"])

    def test_lessons_default_page_size_and_next_pages(self) -> None:
        self.make_lessons(14)  # вместе с уроком из setUp — 15
        url = reverse("materials:lesson-list")
        first = self.client.get(url).json()
        self.assertEqual(first["count"], 15)
        self.assertEqual(len(first["results"]), 10)
        self.assertIsNotNone(first["next"])
        second = self.client.get(url, {"page": 2}).json()
        self.assertEqual(len(second["results"]), 5)
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])
        ids = [x["id"] for x in first["results"]] + [x["id"] for x in second["results"]]
        self.assertEqual(len(set(ids)), 15)
        self.assertEqual(ids, sorted(ids))

    def test_courses_page_size_param(self) -> None:
        self.make_courses(11)
        url = reverse("materials:courses-list")
        self.assertEqual(len(self.client.get(url).json()["results"]), 10)
        body = self.client.get(url, {"page_size": 5}).json()
        self.assertEqual(len(body["results"]), 5)
        self.assertEqual(body["count"], 12)

    def test_page_size_is_capped(self) -> None:
        self.make_lessons(59)  # всего 60
        url = reverse("materials:lesson-list")
        body = self.client.get(url, {"page_size": 100}).json()
        self.assertEqual(body["count"], 60)
        self.assertEqual(len(body["results"]), 50)
        self.assertEqual(len(self.client.get(url, {"page_size": 20}).json()["results"]), 20)

    def test_invalid_page_returns_404(self) -> None:
        response = self.client.get(reverse("materials:lesson-list"), {"page": 99})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_moderator_pagination_sees_all(self) -> None:
        self.make_courses(20)
        self.client.force_authenticate(user=self.moder)
        body = self.client.get(reverse("materials:courses-list")).json()
        self.assertEqual(body["count"], 21)
