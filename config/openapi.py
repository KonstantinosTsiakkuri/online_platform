"""Общие части OpenAPI-документации: типовые ответы об ошибках."""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiResponse
from rest_framework import serializers


class DetailSerializer(serializers.Serializer[Any]):
    """Тело ошибки DRF: {"detail": "..."}."""

    detail = serializers.CharField(help_text="Описание ошибки")


class MessageSerializer(serializers.Serializer[Any]):
    """Тело успешного ответа: {"message": "..."}."""

    message = serializers.CharField(help_text="Результат операции")


def _detail(description: str, example: str, name: str) -> OpenApiResponse:
    return OpenApiResponse(
        response=DetailSerializer,
        description=description,
        examples=[OpenApiExample(name, value={"detail": example}, response_only=True)],
    )


def validation_error(description: str = "Ошибка валидации", example: dict[str, Any] | None = None) -> OpenApiResponse:
    return OpenApiResponse(
        response=OpenApiTypes.OBJECT,
        description=description,
        examples=[
            OpenApiExample(
                "Ошибка валидации",
                value=example or {"поле": ["Текст ошибки."]},
                response_only=True,
            )
        ],
    )


UNAUTHORIZED = _detail(
    "Не передан или недействителен JWT-токен", "Учетные данные не были предоставлены.", "Нет токена"
)
FORBIDDEN = _detail("Недостаточно прав для действия", "У вас нет прав для выполнения данного действия.", "Нет прав")
NOT_FOUND = _detail("Объект не найден (или скрыт от текущего пользователя)", "Не найдено.", "Не найдено")
BAD_GATEWAY = _detail(
    "Платёжный сервис Stripe вернул ошибку или недоступен",
    "Ошибка платёжного сервиса: Invalid API Key provided.",
    "Ошибка Stripe",
)
