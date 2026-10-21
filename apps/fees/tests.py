from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, Student
from apps.fees.forms import FeePaymentForm
from apps.fees.models import FeeCharge, FeePayment, student_fee_totals


class FeeTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=timezone.datetime(2026, 8, 1).date(),
            end_date=timezone.datetime(2027, 7, 31).date(),
            is_active=True,
        )
        cls.student = Student.objects.create(
            admission_number="A-100",
            first_name="Sam",
            last_name="Student",
            is_active=True,
        )
        user_model = get_user_model()
        cls.office_user = user_model.objects.create_user(
            username="office-fees", password="test-password", role="office"
        )
        cls.teacher_user = user_model.objects.create_user(
            username="teacher-fees", password="test-password", role="teacher"
        )


class FeeTotalsTests(FeeTestDataMixin, TestCase):
    def test_totals_use_decimal_arithmetic_and_include_paid_amounts(self):
        FeeCharge.objects.create(
            student=self.student,
            academic_year=self.year,
            description="Tuition",
            amount=Decimal("100.10"),
        )
        FeeCharge.objects.create(
            student=self.student,
            academic_year=self.year,
            description="Books",
            amount=Decimal("25.20"),
        )
        FeePayment.objects.create(
            student=self.student,
            academic_year=self.year,
            amount=Decimal("80.30"),
            payment_date=timezone.localdate(),
            method=FeePayment.Method.CASH,
        )
        self.assertEqual(
            student_fee_totals(self.student, self.year),
            {
                "charged": Decimal("125.30"),
                "paid": Decimal("80.30"),
                "outstanding": Decimal("45.00"),
            },
        )

    def test_payment_model_rejects_destructive_correction(self):
        payment = FeePayment.objects.create(
            student=self.student,
            academic_year=self.year,
            amount=Decimal("10.00"),
        )
        payment.amount = Decimal("9.00")
        with self.assertRaises(ValidationError):
            payment.save()
        with self.assertRaises(ValidationError):
            payment.delete()

    def test_invalid_amounts_are_rejected(self):
        charge = FeeCharge(
            student=self.student,
            academic_year=self.year,
            description="Invalid",
            amount=Decimal("0.00"),
        )
        with self.assertRaises(ValidationError):
            charge.full_clean()

        form = FeePaymentForm(
            data={
                "student": self.student.pk,
                "academic_year": self.year.pk,
                "amount": "-1.00",
                "payment_date": timezone.localdate().isoformat(),
                "method": FeePayment.Method.CASH,
                "receipt_reference": "",
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_payment_cannot_exceed_outstanding_balance(self):
        FeeCharge.objects.create(
            student=self.student,
            academic_year=self.year,
            description="Tuition",
            amount=Decimal("25.00"),
        )
        form = FeePaymentForm(
            data={
                "student": self.student.pk,
                "academic_year": self.year.pk,
                "amount": "25.01",
                "payment_date": timezone.localdate().isoformat(),
                "method": FeePayment.Method.CASH,
                "receipt_reference": "",
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_receipt_reference_is_generated(self):
        payment = FeePayment.objects.create(student=self.student, amount=Decimal("1.00"))
        self.assertTrue(payment.receipt_reference.startswith("FEE-"))
        self.assertEqual(len(payment.receipt_reference), 36)


class FeePermissionTests(FeeTestDataMixin, TestCase):
    def test_office_can_view_dues_and_principal_role_is_supported(self):
        self.client.force_login(self.office_user)
        self.assertEqual(self.client.get(reverse("fees:dues")).status_code, 200)

        self.office_user.role = "principal"
        self.office_user.save()
        self.assertEqual(self.client.get(reverse("fees:dues")).status_code, 200)

    def test_teacher_cannot_access_fee_records(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("fees:dues")).status_code, 403)
        self.assertEqual(self.client.get(reverse("fees:charge-create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("fees:payment-create")).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("fees:dues"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response.url)
