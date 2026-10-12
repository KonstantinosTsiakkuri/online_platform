from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager["User"]):
    """Менеджер пользователей, в котором вход выполняется по email, а не по username."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> "User":
        if not email:
            raise ValueError("Необходимо указать email")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields: Any) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Суперпользователь должен иметь is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Суперпользователь должен иметь is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None  # type: ignore[assignment]
    email = models.EmailField(unique=True, verbose_name="Email")
    phone = models.CharField(max_length=35, blank=True, null=True, verbose_name="Телефон")
    city = models.CharField(max_length=100, blank=True, null=True, verbose_name="Город")
    avatar = models.ImageField(upload_to="users/avatars/", blank=True, null=True, verbose_name="Аватар")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()  # type: ignore[assignment]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self) -> str:
        return self.email


class Payment(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Наличные"
        TRANSFER = "transfer", "Перевод на счёт"
        STRIPE = "stripe", "Онлайн-оплата (Stripe)"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Не оплачен"
        PAID = "paid", "Оплачен"
        NO_PAYMENT_REQUIRED = "no_payment_required", "Оплата не требуется"
        EXPIRED = "expired", "Сессия истекла"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
        verbose_name="Пользователь",
    )
    payment_date = models.DateField(verbose_name="Дата оплаты")
    paid_course = models.ForeignKey(
        "materials.Course",
        on_delete=models.SET_NULL,
        related_name="payments",
        blank=True,
        null=True,
        verbose_name="Оплаченный курс",
    )
    paid_lesson = models.ForeignKey(
        "materials.Lesson",
        on_delete=models.SET_NULL,
        related_name="payments",
        blank=True,
        null=True,
        verbose_name="Оплаченный урок",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Сумма оплаты")
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        verbose_name="Способ оплаты",
    )
    stripe_product_id = models.CharField(max_length=255, blank=True, default="", verbose_name="Stripe: ID продукта")
    stripe_price_id = models.CharField(max_length=255, blank=True, default="", verbose_name="Stripe: ID цены")
    stripe_session_id = models.CharField(max_length=255, blank=True, default="", verbose_name="Stripe: ID сессии")
    payment_link = models.URLField(max_length=1000, blank=True, null=True, verbose_name="Ссылка на оплату")
    payment_status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        verbose_name="Статус оплаты",
    )

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-payment_date", "-id"]

    def __str__(self) -> str:
        target = self.paid_course or self.paid_lesson or "—"
        return f"{self.user} — {target}: {self.amount} ({self.payment_date})"
