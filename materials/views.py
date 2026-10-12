from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from config.openapi import FORBIDDEN, NOT_FOUND, UNAUTHORIZED, MessageSerializer, validation_error
from users.permissions import IsModer, IsOwner, IsSuperuser, is_moderator

from .models import Course, Lesson, Subscription
from .paginators import MaterialsPagination
from .serializers import CourseSerializer, LessonSerializer, SubscriptionRequestSerializer
from .tasks import send_course_update_email

# Наборы прав (операторы DRF: & — И, | — ИЛИ, ~ — НЕ).
CAN_CREATE = IsAuthenticated & ~IsModer
CAN_VIEW_EDIT = IsAuthenticated & (IsModer | IsOwner | IsSuperuser)
CAN_DELETE = IsAuthenticated & ((~IsModer & IsOwner) | IsSuperuser)

COURSES_TAG = "Курсы"
LESSONS_TAG = "Уроки"
SUBSCRIPTIONS_TAG = "Подписки"

# Письмо подписчикам не отправляется, если курс уже обновлялся менее 4 часов назад
NOTIFY_INTERVAL = timedelta(hours=4)

LINK_RULE = (
    "Во всех текстовых полях допускаются только ссылки на youtube.com (и его поддомены); "
    "иначе возвращается 400 с описанием недопустимой ссылки."
)
EDIT_RULE = "Доступно владельцу, модератору и суперпользователю."
VISIBILITY_RULE = "Обычный пользователь видит только свои объекты, модератор и суперпользователь — все."
LESSON_ID = OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID урока")


def filter_by_owner(queryset: QuerySet[Any], user: Any) -> QuerySet[Any]:
    """Модератор и суперпользователь видят всё, остальные — только свои объекты."""
    if not user.is_authenticated:  # например, при генерации OpenAPI-схемы
        return queryset.none()
    if user.is_superuser or is_moderator(user):
        return queryset
    return queryset.filter(owner=user)


@extend_schema_view(
    list=extend_schema(
        tags=[COURSES_TAG],
        summary="Список курсов",
        description=f"Постраничный список курсов с вложенными уроками. {VISIBILITY_RULE}",
        responses={200: CourseSerializer(many=True), 401: UNAUTHORIZED},
    ),
    create=extend_schema(
        tags=[COURSES_TAG],
        summary="Создать курс",
        description=(
            "Создаёт курс; владельцем становится текущий пользователь (поле `owner` из тела игнорируется). "
            f"Модераторам создание запрещено. {LINK_RULE} Цена (`price`) нужна для онлайн-оплаты."
        ),
        responses={
            201: CourseSerializer,
            400: validation_error(
                example={"description": ['Поле "Описание" может содержать только ссылки на youtube.com.']}
            ),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
        },
    ),
    retrieve=extend_schema(
        tags=[COURSES_TAG],
        summary="Получить курс",
        description=(
            "Курс с вложенным списком уроков, `lessons_count` и признаком подписки `is_subscribed`. "
            "Доступно владельцу, модератору и суперпользователю; чужой курс для обычного пользователя — 404."
        ),
        responses={200: CourseSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
    update=extend_schema(
        tags=[COURSES_TAG],
        summary="Обновить курс целиком",
        description=f"Доступно владельцу, модератору и суперпользователю. {LINK_RULE}",
        responses={200: CourseSerializer, 400: validation_error(), 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
    partial_update=extend_schema(
        tags=[COURSES_TAG],
        summary="Обновить курс частично",
        description=f"Передаются только изменяемые поля. {EDIT_RULE} {LINK_RULE}",
        responses={200: CourseSerializer, 400: validation_error(), 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
    destroy=extend_schema(
        tags=[COURSES_TAG],
        summary="Удалить курс",
        description=(
            "Удаляет курс вместе с его уроками. Доступно владельцу и суперпользователю; "
            "модератору удаление запрещено (403)."
        ),
        responses={204: OpenApiResponse(description="Курс удалён"), 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
    ),
)
class CourseViewSet(viewsets.ModelViewSet[Course]):
    """CRUD для курсов: list, retrieve, create, update, partial_update, destroy."""

    queryset = Course.objects.prefetch_related("lessons").order_by("id")
    serializer_class = CourseSerializer
    pagination_class = MaterialsPagination

    def get_queryset(self) -> QuerySet[Course]:
        return filter_by_owner(super().get_queryset(), self.request.user)

    def perform_create(self, serializer: BaseSerializer[Course]) -> None:
        serializer.save(owner=self.request.user)

    def perform_update(self, serializer: BaseSerializer[Course]) -> None:
        # Время предыдущего обновления запоминаем ДО сохранения: save() перезапишет updated_at (auto_now)
        previous_update = serializer.instance.updated_at if serializer.instance else None
        course = serializer.save()
        if previous_update is not None and timezone.now() - previous_update < NOTIFY_INTERVAL:
            return  # курс обновлялся менее 4 часов назад — подписчиков не беспокоим
        # Задача ставится в очередь только после фиксации транзакции. robust=True: если брокер недоступен,
        # ошибка пишется в лог, а клиент получает успешный ответ (курс уже сохранён).
        transaction.on_commit(lambda: send_course_update_email.delay(course.pk), robust=True)

    def get_permissions(self) -> list[Any]:
        permission: Any
        if self.action == "create":
            permission = CAN_CREATE
        elif self.action in ("retrieve", "update", "partial_update"):
            permission = CAN_VIEW_EDIT
        elif self.action == "destroy":
            permission = CAN_DELETE
        else:  # list
            permission = IsAuthenticated
        return [permission()]


@extend_schema(
    tags=[LESSONS_TAG],
    summary="Список уроков",
    description=f"Постраничный список уроков. {VISIBILITY_RULE}",
    responses={200: LessonSerializer(many=True), 401: UNAUTHORIZED},
)
class LessonListAPIView(generics.ListAPIView[Lesson]):
    queryset = Lesson.objects.order_by("id")
    serializer_class = LessonSerializer
    pagination_class = MaterialsPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


@extend_schema(
    tags=[LESSONS_TAG],
    summary="Создать урок",
    description=(
        "Создаёт урок в курсе; владельцем становится текущий пользователь (поле `owner` из тела игнорируется). "
        f"Модераторам создание запрещено. {LINK_RULE}"
    ),
    responses={
        201: LessonSerializer,
        400: validation_error(
            example={
                "video_url": [
                    'Поле "Ссылка на видео" может содержать только ссылки на youtube.com. '
                    "Недопустимая ссылка: https://vimeo.com/1"
                ]
            }
        ),
        401: UNAUTHORIZED,
        403: FORBIDDEN,
    },
)
class LessonCreateAPIView(generics.CreateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_CREATE]

    def perform_create(self, serializer: BaseSerializer[Lesson]) -> None:
        serializer.save(owner=self.request.user)


@extend_schema(
    tags=[LESSONS_TAG],
    summary="Получить урок",
    description="Доступно владельцу, модератору и суперпользователю; чужой урок для обычного пользователя — 404.",
    parameters=[LESSON_ID],
    responses={200: LessonSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
)
class LessonRetrieveAPIView(generics.RetrieveAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_VIEW_EDIT]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


@extend_schema_view(
    put=extend_schema(
        tags=[LESSONS_TAG],
        summary="Обновить урок целиком",
        description=f"Доступно владельцу, модератору и суперпользователю. {LINK_RULE}",
        parameters=[LESSON_ID],
        responses={200: LessonSerializer, 400: validation_error(), 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
    patch=extend_schema(
        tags=[LESSONS_TAG],
        summary="Обновить урок частично",
        description=f"Передаются только изменяемые поля. {EDIT_RULE} {LINK_RULE}",
        parameters=[LESSON_ID],
        responses={200: LessonSerializer, 400: validation_error(), 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
)
class LessonUpdateAPIView(generics.UpdateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_VIEW_EDIT]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


@extend_schema(
    tags=[LESSONS_TAG],
    summary="Удалить урок",
    description="Доступно владельцу и суперпользователю; модератору удаление запрещено (403).",
    parameters=[LESSON_ID],
    responses={204: OpenApiResponse(description="Урок удалён"), 401: UNAUTHORIZED, 403: FORBIDDEN, 404: NOT_FOUND},
)
class LessonDestroyAPIView(generics.DestroyAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_DELETE]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


@extend_schema(
    tags=[SUBSCRIPTIONS_TAG],
    summary="Подписаться на курс / отписаться",
    description=(
        "Переключатель подписки текущего пользователя на курс: если подписки нет — создаёт её (201), "
        "если есть — удаляет (200). Подписаться можно на любой существующий курс."
    ),
    request=SubscriptionRequestSerializer,
    examples=[OpenApiExample("Запрос", value={"course_id": 1}, request_only=True)],
    responses={
        201: OpenApiResponse(
            response=MessageSerializer,
            description="Подписка добавлена",
            examples=[OpenApiExample("Подписка добавлена", value={"message": "Подписка добавлена"})],
        ),
        200: OpenApiResponse(
            response=MessageSerializer,
            description="Подписка удалена",
            examples=[OpenApiExample("Подписка удалена", value={"message": "Подписка удалена"})],
        ),
        400: validation_error("Не передан `course_id`", {"course_id": "Не передан обязательный параметр course_id."}),
        401: UNAUTHORIZED,
        404: NOT_FOUND,
    },
)
class SubscriptionAPIView(APIView):
    """POST {"course_id": N}: переключает подписку текущего пользователя на курс."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        user: Any = request.user
        data: Any = request.data
        course_id = data.get("course_id")
        if course_id in (None, ""):
            return Response(
                {"course_id": "Не передан обязательный параметр course_id."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            course = get_object_or_404(Course, pk=course_id)
        except (ValueError, TypeError):
            return Response({"detail": "Курс не найден."}, status=status.HTTP_404_NOT_FOUND)

        subscription, created = Subscription.objects.get_or_create(user=user, course=course)
        if created:
            return Response({"message": "Подписка добавлена"}, status=status.HTTP_201_CREATED)
        subscription.delete()
        return Response({"message": "Подписка удалена"}, status=status.HTTP_200_OK)
