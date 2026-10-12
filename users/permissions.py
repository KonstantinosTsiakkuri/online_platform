from typing import Any

from django.contrib.auth.models import AnonymousUser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import User

MODERATORS_GROUP = "moderators"


def is_moderator(user: User | AnonymousUser) -> bool:
    return bool(user and user.is_authenticated and user.groups.filter(name=MODERATORS_GROUP).exists())


class IsModer(BasePermission):
    """Пользователь состоит в группе «moderators».

    has_object_permission реализован намеренно: у BasePermission он всегда возвращает True,
    поэтому без него ~IsModer на уровне объекта всегда давал бы False.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return is_moderator(request.user)

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        return is_moderator(request.user)


class IsOwner(BasePermission):
    """Пользователь является владельцем объекта (поле owner)."""

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        return bool(obj.owner == request.user)


class IsSuperuser(BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return bool(request.user and request.user.is_superuser)

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        return bool(request.user and request.user.is_superuser)


class IsSelf(BasePermission):
    """Объект — сам пользователь; staff и суперпользователь могут всё."""

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        user = request.user
        return bool(obj == user or user.is_staff or user.is_superuser)
