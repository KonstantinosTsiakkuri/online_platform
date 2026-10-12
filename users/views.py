from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, mixins, viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated

from .models import Payment, User
from .permissions import IsSelf
from .serializers import PaymentSerializer, UserRegisterSerializer, UserSerializer


class PaymentListAPIView(generics.ListAPIView[Payment]):
    """Список платежей. Фильтры: paid_course, paid_lesson, payment_method; сортировка: ordering=[-]payment_date."""

    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["paid_course", "paid_lesson", "payment_method"]
    ordering_fields = ["payment_date"]


class UserRegisterAPIView(generics.CreateAPIView[User]):
    """Регистрация: открыта для всех, пароль хешируется, пользователь активен."""

    queryset = User.objects.all()
    serializer_class = UserRegisterSerializer
    permission_classes = (AllowAny,)


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

    def get_permissions(self) -> list[BasePermission]:
        if self.action in ("update", "partial_update", "destroy"):
            return [IsAuthenticated(), IsSelf()]
        return [IsAuthenticated()]
