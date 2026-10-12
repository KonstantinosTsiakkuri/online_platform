from typing import Any

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer
from rest_framework.views import APIView

from users.permissions import IsModer, IsOwner, IsSuperuser, is_moderator

from .models import Course, Lesson, Subscription
from .paginators import MaterialsPagination
from .serializers import CourseSerializer, LessonSerializer

# Наборы прав (операторы DRF: & — И, | — ИЛИ, ~ — НЕ).
CAN_CREATE = IsAuthenticated & ~IsModer
CAN_VIEW_EDIT = IsAuthenticated & (IsModer | IsOwner | IsSuperuser)
CAN_DELETE = IsAuthenticated & ((~IsModer & IsOwner) | IsSuperuser)


def filter_by_owner(queryset: QuerySet[Any], user: Any) -> QuerySet[Any]:
    """Модератор и суперпользователь видят всё, остальные — только свои объекты."""
    if user.is_superuser or is_moderator(user):
        return queryset
    return queryset.filter(owner=user)


class CourseViewSet(viewsets.ModelViewSet[Course]):
    """CRUD для курсов: list, retrieve, create, update, partial_update, destroy."""

    queryset = Course.objects.prefetch_related("lessons").order_by("id")
    serializer_class = CourseSerializer
    pagination_class = MaterialsPagination

    def get_queryset(self) -> QuerySet[Course]:
        return filter_by_owner(super().get_queryset(), self.request.user)

    def perform_create(self, serializer: BaseSerializer[Course]) -> None:
        serializer.save(owner=self.request.user)

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


class LessonListAPIView(generics.ListAPIView[Lesson]):
    queryset = Lesson.objects.order_by("id")
    serializer_class = LessonSerializer
    pagination_class = MaterialsPagination
    permission_classes = [IsAuthenticated]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


class LessonCreateAPIView(generics.CreateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_CREATE]

    def perform_create(self, serializer: BaseSerializer[Lesson]) -> None:
        serializer.save(owner=self.request.user)


class LessonRetrieveAPIView(generics.RetrieveAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_VIEW_EDIT]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


class LessonUpdateAPIView(generics.UpdateAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_VIEW_EDIT]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


class LessonDestroyAPIView(generics.DestroyAPIView[Lesson]):
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
    permission_classes = [CAN_DELETE]

    def get_queryset(self) -> QuerySet[Lesson]:
        return filter_by_owner(super().get_queryset(), self.request.user)


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
