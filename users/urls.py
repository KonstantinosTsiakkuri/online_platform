from django.urls import path
from rest_framework.permissions import AllowAny
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .apps import UsersConfig
from .views import PaymentListAPIView, UserRegisterAPIView, UserViewSet

app_name = UsersConfig.name

router = SimpleRouter()
router.register(r"users", UserViewSet, basename="users")

urlpatterns = [
    path("payments/", PaymentListAPIView.as_view(), name="payment-list"),
    path("users/register/", UserRegisterAPIView.as_view(), name="register"),
    path("users/token/", TokenObtainPairView.as_view(permission_classes=(AllowAny,)), name="token-obtain"),
    path("users/token/refresh/", TokenRefreshView.as_view(permission_classes=(AllowAny,)), name="token-refresh"),
] + router.urls
