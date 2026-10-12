"""Взаимодействие со Stripe. Остальной код проекта напрямую с библиотекой stripe не работает."""

from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict

import stripe
from django.conf import settings


class StripeServiceError(Exception):
    """Любая ошибка при обращении к Stripe (сеть, неверный ключ, неверные параметры и т. д.)."""


class SessionState(TypedDict):
    status: str | None
    payment_status: str | None


def _configure() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise StripeServiceError("Stripe не настроен: задайте STRIPE_SECRET_KEY в .env.")
    stripe.api_key = settings.STRIPE_SECRET_KEY


def amount_to_minor_units(amount: Decimal) -> int:
    """Рубли -> копейки (доллары -> центы): сумма × 100, целое число."""
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_stripe_product(name: str) -> str:
    """Создаёт продукт в Stripe и возвращает его id."""
    _configure()
    try:
        product = stripe.Product.create(name=name)
    except stripe.StripeError as exc:
        raise StripeServiceError(_message(exc)) from exc
    return str(product["id"])


def create_stripe_price(product_id: str, amount: Decimal) -> str:
    """Создаёт цену для продукта; unit_amount передаётся в копейках (центах)."""
    _configure()
    try:
        price = stripe.Price.create(
            currency=settings.STRIPE_CURRENCY,
            unit_amount=amount_to_minor_units(amount),
            product=product_id,
        )
    except stripe.StripeError as exc:
        raise StripeServiceError(_message(exc)) from exc
    return str(price["id"])


def create_stripe_session(price_id: str, success_url: str, cancel_url: str) -> tuple[str, str]:
    """Создаёт Checkout Session (разовый платёж) и возвращает (id сессии, ссылка на оплату)."""
    _configure()
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except stripe.StripeError as exc:
        raise StripeServiceError(_message(exc)) from exc
    return str(session["id"]), str(session["url"])


def retrieve_stripe_session(session_id: str) -> SessionState:
    """Получает сессию из Stripe и возвращает её status и payment_status."""
    _configure()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.StripeError as exc:
        raise StripeServiceError(_message(exc)) from exc
    return {"status": session["status"], "payment_status": session["payment_status"]}


def _message(exc: stripe.StripeError) -> str:
    return str(getattr(exc, "user_message", None) or exc)
