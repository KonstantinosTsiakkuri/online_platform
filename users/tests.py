"""Тесты оплаты через Stripe и документации API. Stripe везде замокан: реальных запросов нет."""

from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import stripe
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from materials.models import Course

from . import services
from .models import Payment, User

TEST_SETTINGS = {
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_CURRENCY": "rub",
    "STRIPE_SUCCESS_URL": "http://testserver/success?session_id={CHECKOUT_SESSION_ID}",
    "STRIPE_CANCEL_URL": "http://testserver/cancel",
    "PASSWORD_HASHERS": ["django.contrib.auth.hashers.MD5PasswordHasher"],
}


@override_settings(**TEST_SETTINGS)
class StripeServicesTests(APITestCase):
    @patch("users.services.stripe.Product.create")
    def test_create_product(self, product_create: MagicMock) -> None:
        product_create.return_value = {"id": "prod_1"}
        self.assertEqual(services.create_stripe_product("Python"), "prod_1")
        product_create.assert_called_once_with(name="Python")

    @patch("users.services.stripe.Price.create")
    def test_price_is_sent_in_minor_units(self, price_create: MagicMock) -> None:
        price_create.return_value = {"id": "price_1"}
        self.assertEqual(services.create_stripe_price("prod_1", Decimal("1990.50")), "price_1")
        price_create.assert_called_once_with(currency="rub", unit_amount=199050, product="prod_1")
        self.assertIsInstance(price_create.call_args.kwargs["unit_amount"], int)

    def test_amount_to_minor_units(self) -> None:
        self.assertEqual(services.amount_to_minor_units(Decimal("100")), 10000)
        self.assertEqual(services.amount_to_minor_units(Decimal("0.01")), 1)
        self.assertEqual(services.amount_to_minor_units(Decimal("19.999")), 2000)  # округление копеек

    @override_settings(STRIPE_CURRENCY="usd")
    @patch("users.services.stripe.Price.create")
    def test_currency_comes_from_settings(self, price_create: MagicMock) -> None:
        price_create.return_value = {"id": "price_1"}
        services.create_stripe_price("prod_1", Decimal("5"))
        self.assertEqual(price_create.call_args.kwargs["currency"], "usd")

    @patch("users.services.stripe.checkout.Session.create")
    def test_create_session(self, session_create: MagicMock) -> None:
        session_create.return_value = {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}
        result = services.create_stripe_session("price_1", "http://ok", "http://no")
        self.assertEqual(result, ("cs_1", "https://checkout.stripe.com/c/pay/cs_1"))
        session_create.assert_called_once_with(
            mode="payment",
            line_items=[{"price": "price_1", "quantity": 1}],
            success_url="http://ok",
            cancel_url="http://no",
        )

    @patch("users.services.stripe.checkout.Session.retrieve")
    def test_retrieve_session(self, retrieve: MagicMock) -> None:
        retrieve.return_value = {"status": "complete", "payment_status": "paid"}
        self.assertEqual(services.retrieve_stripe_session("cs_1"), {"status": "complete", "payment_status": "paid"})
        retrieve.assert_called_once_with("cs_1")

    def test_stripe_errors_become_service_error(self) -> None:
        error = stripe.StripeError("boom")
        calls: list[Any] = [
            ("users.services.stripe.Product.create", lambda: services.create_stripe_product("x")),
            ("users.services.stripe.Price.create", lambda: services.create_stripe_price("p", Decimal("1"))),
            ("users.services.stripe.checkout.Session.create", lambda: services.create_stripe_session("p", "a", "b")),
            ("users.services.stripe.checkout.Session.retrieve", lambda: services.retrieve_stripe_session("cs")),
        ]
        for target, call in calls:
            with patch(target, side_effect=error), self.assertRaises(services.StripeServiceError):
                call()

    @override_settings(STRIPE_SECRET_KEY="")
    def test_missing_key(self) -> None:
        with self.assertRaises(services.StripeServiceError) as ctx:
            services.create_stripe_product("x")
        self.assertIn("STRIPE_SECRET_KEY", str(ctx.exception))


@override_settings(**TEST_SETTINGS)
class PaymentBaseTestCase(APITestCase):
    def setUp(self) -> None:
        self.owner = User.objects.create_user(email="owner@test.com", password="Str0ng-Pass!2026")
        self.buyer = User.objects.create_user(email="buyer@test.com", password="Str0ng-Pass!2026")
        self.other = User.objects.create_user(email="other@test.com", password="Str0ng-Pass!2026")
        self.moder = User.objects.create_user(email="moder@test.com", password="Str0ng-Pass!2026")
        group, _ = Group.objects.get_or_create(name="moderators")
        self.moder.groups.add(group)
        self.admin = User.objects.create_superuser(email="admin@test.com", password="Str0ng-Pass!2026")
        self.course = Course.objects.create(title="Курс Python", price=Decimal("1990.50"), owner=self.owner)
        self.free_course = Course.objects.create(title="Без цены", owner=self.owner)


class PaymentCreateTests(PaymentBaseTestCase):
    url_name = "users:payment-create"

    def setUp(self) -> None:
        super().setUp()
        self.url = reverse(self.url_name)
        self.client.force_authenticate(user=self.buyer)

    def patches(self) -> Any:
        product = patch("users.services.stripe.Product.create", return_value={"id": "prod_42"})
        price = patch("users.services.stripe.Price.create", return_value={"id": "price_42"})
        session = patch(
            "users.services.stripe.checkout.Session.create",
            return_value={"id": "cs_test_42", "url": "https://checkout.stripe.com/c/pay/cs_test_42#fidkdW"},
        )
        return product, price, session

    def test_create_payment_full_flow(self) -> None:
        product, price, session = self.patches()
        with product as product_mock, price as price_mock, session as session_mock:
            response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # цепочка вызовов: продукт -> цена -> сессия
        product_mock.assert_called_once_with(name="Курс Python")
        price_mock.assert_called_once_with(currency="rub", unit_amount=199050, product="prod_42")
        session_mock.assert_called_once_with(
            mode="payment",
            line_items=[{"price": "price_42", "quantity": 1}],
            success_url="http://testserver/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://testserver/cancel",
        )
        # платёж сохранён
        self.assertEqual(Payment.objects.count(), 1)
        payment = Payment.objects.get()
        self.assertEqual(payment.user, self.buyer)
        self.assertEqual(payment.paid_course, self.course)
        self.assertIsNone(payment.paid_lesson)
        self.assertEqual(payment.amount, Decimal("1990.50"))
        self.assertEqual(payment.payment_method, Payment.PaymentMethod.STRIPE)
        self.assertEqual(payment.payment_status, Payment.PaymentStatus.UNPAID)
        self.assertEqual(payment.stripe_product_id, "prod_42")
        self.assertEqual(payment.stripe_price_id, "price_42")
        self.assertEqual(payment.stripe_session_id, "cs_test_42")
        self.assertEqual(payment.payment_link, "https://checkout.stripe.com/c/pay/cs_test_42#fidkdW")
        # ответ API
        body = response.json()
        self.assertEqual(body["id"], payment.pk)
        self.assertEqual(body["payment_link"], payment.payment_link)
        self.assertEqual(body["stripe_session_id"], "cs_test_42")
        self.assertEqual(body["payment_status"], "unpaid")
        self.assertEqual(body["paid_course"], self.course.pk)

    def test_user_is_taken_from_request_not_body(self) -> None:
        product, price, session = self.patches()
        with product, price, session:
            self.client.post(self.url, {"course_id": self.course.pk, "user": self.other.pk}, format="json")
        self.assertEqual(Payment.objects.get().user, self.buyer)

    def test_validation_errors(self) -> None:
        for body in ({}, {"course_id": "abc"}, {"course_id": 0}):
            response = self.client.post(self.url, body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, body)
            self.assertIn("course_id", response.json())
        self.assertEqual(Payment.objects.count(), 0)

    def test_unknown_course(self) -> None:
        with patch("users.services.stripe.Product.create") as product:
            response = self.client.post(self.url, {"course_id": 99999}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        product.assert_not_called()

    def test_course_without_price(self) -> None:
        with patch("users.services.stripe.Product.create") as product:
            response = self.client.post(self.url, {"course_id": self.free_course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("course_id", response.json())
        product.assert_not_called()
        self.assertEqual(Payment.objects.count(), 0)

    def test_anonymous(self) -> None:
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_stripe_error_on_product(self) -> None:
        with patch("users.services.stripe.Product.create", side_effect=stripe.StripeError("Invalid API Key")):
            response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Invalid API Key", response.json()["detail"])
        self.assertEqual(Payment.objects.count(), 0)

    def test_stripe_error_on_session_saves_nothing(self) -> None:
        with (
            patch("users.services.stripe.Product.create", return_value={"id": "prod_1"}),
            patch("users.services.stripe.Price.create", return_value={"id": "price_1"}),
            patch("users.services.stripe.checkout.Session.create", side_effect=stripe.StripeError("Network down")),
        ):
            response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Network down", response.json()["detail"])
        self.assertEqual(Payment.objects.count(), 0)

    def test_stripe_error_on_price(self) -> None:
        with (
            patch("users.services.stripe.Product.create", return_value={"id": "prod_1"}),
            patch("users.services.stripe.Price.create", side_effect=stripe.StripeError("Bad amount")),
            patch("users.services.stripe.checkout.Session.create") as session,
        ):
            response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        session.assert_not_called()
        self.assertEqual(Payment.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY="")
    def test_stripe_not_configured(self) -> None:
        response = self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("STRIPE_SECRET_KEY", response.json()["detail"])

    def test_database_failure_after_stripe_rolls_back(self) -> None:
        product, price, session = self.patches()
        with product, price, session, patch("users.views.Payment.objects.create", side_effect=RuntimeError("db")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, {"course_id": self.course.pk}, format="json")
        self.assertEqual(Payment.objects.count(), 0)


class PaymentStatusTests(PaymentBaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.payment = Payment.objects.create(
            user=self.buyer,
            paid_course=self.course,
            amount=Decimal("1990.50"),
            payment_date="2026-05-01",
            payment_method=Payment.PaymentMethod.STRIPE,
            stripe_product_id="prod_1",
            stripe_price_id="price_1",
            stripe_session_id="cs_test_1",
            payment_link="https://checkout.stripe.com/c/pay/cs_test_1",
        )
        self.url = reverse("users:payment-status", args=[self.payment.pk])
        self.client.force_authenticate(user=self.buyer)

    def status_with(self, session: dict[str, Any]) -> Any:
        with patch("users.services.stripe.checkout.Session.retrieve", return_value=session) as retrieve:
            response = self.client.get(self.url)
        retrieve.assert_called_once_with("cs_test_1")
        return response

    def test_paid_is_synced(self) -> None:
        response = self.status_with({"status": "complete", "payment_status": "paid"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["payment_status"], "paid")
        self.assertEqual(response.json()["session_status"], "complete")
        self.assertEqual(response.json()["id"], self.payment.pk)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, Payment.PaymentStatus.PAID)

    def test_unpaid_stays_unpaid(self) -> None:
        response = self.status_with({"status": "open", "payment_status": "unpaid"})
        self.assertEqual(response.json()["payment_status"], "unpaid")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, Payment.PaymentStatus.UNPAID)

    def test_expired_session(self) -> None:
        response = self.status_with({"status": "expired", "payment_status": "unpaid"})
        self.assertEqual(response.json()["payment_status"], "expired")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, Payment.PaymentStatus.EXPIRED)

    def test_no_payment_required(self) -> None:
        response = self.status_with({"status": "complete", "payment_status": "no_payment_required"})
        self.assertEqual(response.json()["payment_status"], "no_payment_required")

    def test_status_can_change_back_and_forth(self) -> None:
        self.status_with({"status": "complete", "payment_status": "paid"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, "paid")

    def test_stripe_error(self) -> None:
        with patch("users.services.stripe.checkout.Session.retrieve", side_effect=stripe.StripeError("No such")):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("No such", response.json()["detail"])
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.payment_status, Payment.PaymentStatus.UNPAID)

    def test_other_user_forbidden(self) -> None:
        self.client.force_authenticate(user=self.other)
        with patch("users.services.stripe.checkout.Session.retrieve") as retrieve:
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        retrieve.assert_not_called()

    def test_moderator_and_admin_allowed(self) -> None:
        for user in (self.moder, self.admin):
            self.client.force_authenticate(user=user)
            response = self.status_with({"status": "complete", "payment_status": "paid"})
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.email)

    def test_unknown_payment(self) -> None:
        response = self.client.get(reverse("users:payment-status", args=[99999]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_offline_payment_has_no_session(self) -> None:
        cash = Payment.objects.create(
            user=self.buyer,
            amount=Decimal("100"),
            payment_date="2026-05-02",
            payment_method=Payment.PaymentMethod.CASH,
        )
        with patch("users.services.stripe.checkout.Session.retrieve") as retrieve:
            response = self.client.get(reverse("users:payment-status", args=[cash.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        retrieve.assert_not_called()

    def test_anonymous(self) -> None:
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_401_UNAUTHORIZED)


class PaymentListTests(PaymentBaseTestCase):
    def test_payment_list_has_stripe_fields_and_filters_by_new_method(self) -> None:
        Payment.objects.create(
            user=self.buyer, amount=1, payment_date="2026-05-02", payment_method=Payment.PaymentMethod.CASH
        )
        Payment.objects.create(
            user=self.buyer,
            amount=2,
            payment_date="2026-05-03",
            payment_method=Payment.PaymentMethod.STRIPE,
            payment_link="https://checkout.stripe.com/x",
        )
        self.client.force_authenticate(user=self.buyer)
        rows = self.client.get(reverse("users:payment-list"), {"payment_method": "stripe"}).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payment_link"], "https://checkout.stripe.com/x")
        self.assertEqual(rows[0]["payment_status"], "unpaid")


class ApiDocumentationTests(APITestCase):
    def test_schema_and_ui_are_public(self) -> None:
        for name in ("schema", "swagger-ui", "redoc"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, status.HTTP_200_OK, name)

    def test_schema_covers_all_endpoints_and_bearer_auth(self) -> None:
        response = self.client.get(reverse("schema"), {"format": "json"})
        schema = response.json()
        self.assertIn("jwtAuth", schema["components"]["securitySchemes"])
        expected = {
            "/courses/",
            "/courses/{id}/",
            "/courses/subscribe/",
            "/lessons/",
            "/lessons/create/",
            "/lessons/{id}/",
            "/lessons/{id}/update/",
            "/lessons/{id}/delete/",
            "/payments/",
            "/payments/create/",
            "/payments/{id}/status/",
            "/users/",
            "/users/{id}/",
            "/users/register/",
            "/users/token/",
            "/users/token/refresh/",
        }
        self.assertEqual(expected, set(schema["paths"]))
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                self.assertTrue(operation.get("summary"), f"{method} {path}: нет summary")
                self.assertTrue(operation.get("description"), f"{method} {path}: нет description")
                self.assertTrue(operation.get("tags"), f"{method} {path}: нет тегов")
