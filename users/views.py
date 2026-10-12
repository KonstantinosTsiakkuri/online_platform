from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.filters import OrderingFilter

from .models import Payment
from .serializers import PaymentSerializer


class PaymentListAPIView(generics.ListAPIView[Payment]):
    """Список платежей. Фильтры: paid_course, paid_lesson, payment_method; сортировка: ordering=[-]payment_date."""

    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["paid_course", "paid_lesson", "payment_method"]
    ordering_fields = ["payment_date"]
