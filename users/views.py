from typing import Any

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import generics, mixins, status, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from config.openapi import BAD_GATEWAY, FORBIDDEN, NOT_FOUND, UNAUTHORIZED, DetailSerializer, validation_error
from materials.models import Course

from . import services
from .models import Payment, User
from .permissions import IsPaymentOwnerOrStaff, IsSelf
from .serializers import (
    PaymentCreateSerializer,
    PaymentSerializer,
    PaymentStatusSerializer,
    TokenAccessSerializer,
    TokenPairSerializer,
    UserRegisterSerializer,
    UserSerializer,
)

AUTH_TAG = "Аутентификация"
USERS_TAG = "Пользователи"
PAYMENTS_TAG = "Платежи"


@extend_schema(
    tags=[AUTH_TAG],
    auth=[],
    summary="Получить пару JWT-токенов",
    description=(
        "Обмен email и пароля на пару токенов: `access` (короткоживущий, передаётся в заголовке "
        "`Authorization: Bearer <access>`) и `refresh` (для получения нового `access`)."
    ),
    responses={
        200: OpenApiResponse(response=TokenPairSerializer, description="Пара токенов (`access` и `refresh`)"),
        400: validation_error("Не переданы email или пароль", {"email": ["Обязательное поле."]}),
        401: OpenApiResponse(
            response=DetailSerializer,
            description="Неверный email или пароль",
            examples=[
                OpenApiExample(
                    "Неверные данные",
                    value={"detail": "No active account found with the given credentials"},
                    response_only=True,
                )
            ],
        ),
    },
)
class UserTokenObtainPairView(TokenObtainPairView):
    """Вход открыт: у TokenViewBase пустые authentication_classes и permission_classes."""


@extend_schema(
    tags=[AUTH_TAG],
    auth=[],
    summary="Обновить access-токен",
    description="По действующему `refresh`-токену выдаёт новый `access`-токен.",
    responses={
        200: OpenApiResponse(response=TokenAccessSerializer, description="Новый `access`-токен"),
        400: validation_error("Не передан refresh-токен", {"refresh": ["Обязательное поле."]}),
        401: OpenApiResponse(
            response=DetailSerializer,
            description="Refresh-токен недействителен или просрочен",
            examples=[
                OpenApiExample(
                    "Недействительный токен",
                    value={"detail": "Token is invalid", "code": "token_not_valid"},
                    response_only=True,
                )
            ],
        ),
    },
)
class UserTokenRefreshView(TokenRefreshView):
    """Обновление открыто: у TokenViewBase пустые authentication_classes и permission_classes."""


@extend_schema(
    tags=[PAYMENTS_TAG],
    summary="Список платежей",
    description=(
        "Все платежи (наличные, переводы и онлайн-оплата через Stripe) одним списком, без пагинации. "
        "Поддерживаются фильтрация по курсу, уроку и способу оплаты и сортировка по дате оплаты."
    ),
    parameters=[
        OpenApiParameter(
            "paid_course", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Фильтр: ID оплаченного курса"
        ),
        OpenApiParameter(
            "paid_lesson", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Фильтр: ID оплаченного урока"
        ),
        OpenApiParameter(
            "payment_method",
            OpenApiTypes.STR,
            OpenApiParameter.QUERY,
            description="Фильтр: способ оплаты",
            enum=[value for value, _ in Payment.PaymentMethod.choices],
        ),
        OpenApiParameter(
            "ordering",
            OpenApiTypes.STR,
            OpenApiParameter.QUERY,
            description="Сортировка по дате оплаты: `payment_date` — по возрастанию, `-payment_date` — по убыванию",
            enum=["payment_date", "-payment_date"],
        ),
    ],
    responses={
        200: PaymentSerializer(many=True),
        400: validation_error("Недопустимое значение фильтра", {"payment_method": ["Выберите корректный вариант."]}),
        401: UNAUTHORIZED,
    },
)
class PaymentListAPIView(generics.ListAPIView[Payment]):
    """Список платежей. Фильтры: paid_course, paid_lesson, payment_method; сортировка: ordering=[-]payment_date."""

    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["paid_course", "paid_lesson", "payment_method"]
    ordering_fields = ["payment_date"]


@extend_schema(
    tags=[PAYMENTS_TAG],
    summary="Создать платёж за курс (Stripe Checkout)",
    description=(
        "Создаёт в Stripe продукт (название курса), цену (цена курса в копейках) и Checkout Session, "
        "сохраняет платёж текущего пользователя и возвращает его вместе со ссылкой `payment_link`. "
        "Пользователь переходит по ссылке и оплачивает курс (тестовая карта `4242 4242 4242 4242`). "
        "Если Stripe вернул ошибку, платёж не сохраняется. У курса должна быть указана цена."
    ),
    request=PaymentCreateSerializer,
    responses={
        201: PaymentSerializer,
        400: validation_error(
            "Не передан или некорректен `course_id`, либо у курса не указана цена",
            {"course_id": ["Обязательное поле."]},
        ),
        401: UNAUTHORIZED,
        404: NOT_FOUND,
        502: BAD_GATEWAY,
    },
    examples=[OpenApiExample("Запрос", value={"course_id": 1}, request_only=True)],
)
class PaymentCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        course = get_object_or_404(Course, pk=serializer.validated_data["course_id"])
        if course.price is None or course.price <= 0:
            return Response(
                {"course_id": ["У курса не указана цена, оплата невозможна."]}, status=status.HTTP_400_BAD_REQUEST
            )

        user: Any = request.user
        try:
            with transaction.atomic():
                product_id = services.create_stripe_product(course.title)
                price_id = services.create_stripe_price(product_id, course.price)
                session_id, session_url = services.create_stripe_session(
                    price_id, settings.STRIPE_SUCCESS_URL, settings.STRIPE_CANCEL_URL
                )
                payment = Payment.objects.create(
                    user=user,
                    paid_course=course,
                    amount=course.price,
                    payment_date=timezone.localdate(),
                    payment_method=Payment.PaymentMethod.STRIPE,
                    stripe_product_id=product_id,
                    stripe_price_id=price_id,
                    stripe_session_id=session_id,
                    payment_link=session_url,
                    payment_status=Payment.PaymentStatus.UNPAID,
                )
        except services.StripeServiceError as exc:
            return Response({"detail": f"Ошибка платёжного сервиса: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=[PAYMENTS_TAG],
    summary="Проверить статус платежа",
    description=(
        "Запрашивает у Stripe актуальное состояние Checkout Session, обновляет `payment_status` платежа "
        "в нашей базе и возвращает его. Доступно владельцу платежа, модератору и администратору. "
        "Для платежей без Stripe-сессии (наличные, перевод) возвращается 400."
    ),
    parameters=[OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID платежа")],
    responses={
        200: PaymentStatusSerializer,
        400: validation_error("У платежа нет Stripe-сессии", {"detail": "Это не онлайн-платёж: нет Stripe-сессии."}),
        401: UNAUTHORIZED,
        403: FORBIDDEN,
        404: NOT_FOUND,
        502: BAD_GATEWAY,
    },
)
class PaymentStatusAPIView(APIView):
    permission_classes = [IsAuthenticated, IsPaymentOwnerOrStaff]

    def get(self, request: Request, pk: int) -> Response:
        payment = get_object_or_404(Payment, pk=pk)
        self.check_object_permissions(request, payment)
        if not payment.stripe_session_id:
            return Response({"detail": "Это не онлайн-платёж: нет Stripe-сессии."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            state = services.retrieve_stripe_session(payment.stripe_session_id)
        except services.StripeServiceError as exc:
            return Response({"detail": f"Ошибка платёжного сервиса: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        payment.payment_status = resolve_payment_status(state["status"], state["payment_status"])
        payment.save(update_fields=["payment_status"])
        return Response(
            PaymentStatusSerializer(
                {
                    "id": payment.pk,
                    "payment_status": payment.payment_status,
                    "session_status": state["status"],
                    "stripe_session_id": payment.stripe_session_id,
                    "payment_link": payment.payment_link,
                }
            ).data
        )


def resolve_payment_status(session_status: str | None, stripe_payment_status: str | None) -> str:
    """Переводит статусы Stripe в статус нашего платежа."""
    known = {value for value, _ in Payment.PaymentStatus.choices}
    if stripe_payment_status in ("paid", "no_payment_required"):
        return str(stripe_payment_status)
    if session_status == "expired":
        return Payment.PaymentStatus.EXPIRED.value
    if stripe_payment_status in known:
        return str(stripe_payment_status)
    return Payment.PaymentStatus.UNPAID.value


@extend_schema(
    tags=[USERS_TAG],
    auth=[],
    summary="Регистрация пользователя",
    description=(
        "Создаёт активного пользователя (вход по email). Пароль проверяется валидаторами Django и хранится "
        "в виде хеша. После регистрации можно сразу получить токен в `POST /users/token/`."
    ),
    responses={
        201: UserRegisterSerializer,
        400: validation_error(
            "Email уже занят, пароль слишком простой или не переданы обязательные поля",
            {"email": ["Пользователь с таким email уже существует."]},
        ),
    },
)
class UserRegisterAPIView(generics.CreateAPIView[User]):
    """Регистрация: открыта для всех, пароль хешируется, пользователь активен."""

    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = (AllowAny,)


USER_ID = OpenApiParameter("id", OpenApiTypes.INT, OpenApiParameter.PATH, description="ID пользователя")


@extend_schema_view(
    list=extend_schema(
        tags=[USERS_TAG],
        summary="Список пользователей",
        description="Профили всех пользователей (без паролей). Доступно любому авторизованному пользователю.",
        responses={200: UserSerializer(many=True), 401: UNAUTHORIZED},
    ),
    retrieve=extend_schema(
        tags=[USERS_TAG],
        parameters=[USER_ID],
        summary="Профиль пользователя",
        responses={200: UserSerializer, 401: UNAUTHORIZED, 404: NOT_FOUND},
    ),
    update=extend_schema(
        tags=[USERS_TAG],
        parameters=[USER_ID],
        summary="Полное обновление профиля",
        description="Только свой профиль (staff и суперпользователь — любой). Пароль, права и группы не меняются.",
        responses={
            200: UserSerializer,
            400: validation_error(),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
    partial_update=extend_schema(
        tags=[USERS_TAG],
        parameters=[USER_ID],
        summary="Частичное обновление профиля",
        description="Только свой профиль (staff и суперпользователь — любой). Пароль, права и группы не меняются.",
        responses={
            200: UserSerializer,
            400: validation_error(),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
    destroy=extend_schema(
        tags=[USERS_TAG],
        parameters=[USER_ID],
        summary="Удалить профиль",
        description="Только свой профиль (staff и суперпользователь — любой).",
        responses={
            204: OpenApiResponse(description="Профиль удалён"),
            401: UNAUTHORIZED,
            403: FORBIDDEN,
            404: NOT_FOUND,
        },
    ),
)
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet[User],
):
    """list/retrieve — любому авторизованному; update/destroy — только свой профиль (или staff)."""

    queryset = User.objects.order_by("id")
    lookup_value_regex = r"\d+"
    serializer_class = UserSerializer

    def get_permissions(self) -> list[Any]:
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsSelf()]
        return [IsAuthenticated()]
