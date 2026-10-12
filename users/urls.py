from django.urls import path

from .apps import UsersConfig
from .views import PaymentListAPIView

app_name = UsersConfig.name

urlpatterns = [
    path("payments/", PaymentListAPIView.as_view(), name="payment-list"),
]
