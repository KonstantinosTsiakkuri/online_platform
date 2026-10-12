from typing import Any

from django.db.models import QuerySet
from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import BaseSerializer

from users.permissions import IsModer, IsOwner, IsSuperuser, is_moderator

from .models import Course, Lesson
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

    queryset = Course.objects.prefetch_related("lessons")
    serializer_class = CourseSerializer

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
    queryset = Lesson.objects.all()
    serializer_class = LessonSerializer
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
