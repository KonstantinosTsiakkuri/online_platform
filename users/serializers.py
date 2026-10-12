from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import serializers

from .models import Payment, User


class PaymentSerializer(serializers.ModelSerializer[Payment]):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = (
            "stripe_product_id",
            "stripe_price_id",
            "stripe_session_id",
            "payment_link",
            "payment_status",
        )


class PaymentCreateSerializer(serializers.Serializer[Any]):
    """Тело запроса на создание платежа за курс."""

    course_id = serializers.IntegerField(min_value=1, help_text="ID оплачиваемого курса")


class PaymentStatusSerializer(serializers.Serializer[Any]):
    """Ответ проверки статуса платежа (после синхронизации со Stripe)."""

    id = serializers.IntegerField(help_text="ID платежа в нашей системе")
    payment_status = serializers.ChoiceField(
        choices=Payment.PaymentStatus.choices, help_text="Статус оплаты после синхронизации"
    )
    session_status = serializers.CharField(
        allow_null=True, help_text="Статус Checkout Session в Stripe: open / complete / expired"
    )
    stripe_session_id = serializers.CharField(help_text="ID сессии Stripe")
    payment_link = serializers.URLField(allow_null=True, help_text="Ссылка на страницу оплаты")


class UserSerializer(serializers.ModelSerializer[User]):
    """Профиль пользователя. Пароль, права и группы сюда не входят."""

    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name", "phone", "city", "avatar", "is_active", "date_joined")
        read_only_fields = ("id", "is_active", "date_joined")


class UserRegisterSerializer(serializers.ModelSerializer[User]):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ("id", "email", "password", "first_name", "last_name", "phone", "city")
        read_only_fields = ("id",)
        extra_kwargs: dict[str, Any] = {
            "email": {"validators": []}
        }  # уникальность проверяем сами (с понятным текстом)

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        candidate = User(**{k: v for k, v in attrs.items() if k != "password"})
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        try:
            return User.objects.create_user(**validated_data)
        except IntegrityError as exc:
            raise serializers.ValidationError({"email": "Пользователь с таким email уже существует."}) from exc


class TokenPairSerializer(serializers.Serializer[Any]):
    """Ответ с парой JWT-токенов (для документации)."""

    access = serializers.CharField(help_text="Access-токен: передаётся в заголовке Authorization: Bearer <access>")
    refresh = serializers.CharField(help_text="Refresh-токен: нужен для получения нового access-токена")


class TokenAccessSerializer(serializers.Serializer[Any]):
    """Ответ с новым access-токеном (для документации)."""

    access = serializers.CharField(help_text="Новый access-токен")
