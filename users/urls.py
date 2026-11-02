from django.urls import path
from rest_framework.routers import SimpleRouter

from .apps import UsersConfig
from .views import (
    PaymentCreateAPIView,
    PaymentListAPIView,
    PaymentStatusAPIView,
    UserRegisterAPIView,
    UserTokenObtainPairView,
    UserTokenRefreshView,
    UserViewSet,
)

app_name = UsersConfig.name

router = SimpleRouter()
router.register(r"users", UserViewSet, basename="users")

urlpatterns = [
    path("payments/", PaymentListAPIView.as_view(), name="payment-list"),
    path("payments/create/", PaymentCreateAPIView.as_view(), name="payment-create"),
    path("payments/<int:pk>/status/", PaymentStatusAPIView.as_view(), name="payment-status"),
    path("users/register/", UserRegisterAPIView.as_view(), name="register"),
    path("users/token/", UserTokenObtainPairView.as_view(), name="token-obtain"),
    path("users/token/refresh/", UserTokenRefreshView.as_view(), name="token-refresh"),
] + router.urls
