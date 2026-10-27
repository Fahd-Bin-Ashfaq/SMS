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


class OfficeToolsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta

        from apps.academics.models import Classroom, Enrollment

        cls.today = timezone.localdate()
        cls.year = AcademicYear.objects.create(
            name="Office year",
            start_date=cls.today - timedelta(days=120),
            end_date=cls.today + timedelta(days=200),
            is_active=True,
        )
        cls.classroom = Classroom.objects.create(name="Grade 5", section="A", academic_year=cls.year)
        cls.owing = Student.objects.create(
            admission_number="O-1", first_name="Owes", last_name="Money",
            guardian_name="Parent One", guardian_phone="0300-1234567",
        )
        cls.paid_up = Student.objects.create(admission_number="O-2", first_name="Paid", last_name="Up")
        for student in (cls.owing, cls.paid_up):
            Enrollment.objects.create(student=student, classroom=cls.classroom, academic_year=cls.year)
            FeeCharge.objects.create(
                student=student, academic_year=cls.year, description="Past month",
                amount=Decimal("3000.00"), due_date=cls.today - timedelta(days=5),
            )
            # Billed in advance: not due yet, so it must not count as owed.
            FeeCharge.objects.create(
                student=student, academic_year=cls.year, description="Next month",
                amount=Decimal("3000.00"), due_date=cls.today + timedelta(days=20),
            )
        FeePayment.objects.create(
            student=cls.paid_up, academic_year=cls.year, amount=Decimal("3000.00"),
            payment_date=cls.today, method=FeePayment.Method.CASH,
        )
        user_model = get_user_model()
        cls.office_user = user_model.objects.create_user(username="office-tools", role="office")
        cls.teacher_user = user_model.objects.create_user(username="teacher-tools", role="teacher")

    def test_balances_count_only_charges_that_are_due(self):
        from apps.fees.services import class_summaries, student_balances

        rows = {row["student"].pk: row for row in student_balances(self.today)}
        self.assertEqual(rows[self.owing.pk]["due"], Decimal("3000.00"))
        self.assertEqual(rows[self.paid_up.pk]["due"], Decimal("0.00"))
        [summary] = class_summaries(list(rows.values()))
        self.assertEqual((summary["students"], summary["paid"], summary["due"]), (2, 1, 1))
        self.assertEqual(summary["due_amount"], Decimal("3000.00"))

    def test_dues_page_filters_due_and_paid_students(self):
        self.client.force_login(self.office_user)
        due = self.client.get(reverse("fees:dues"))
        self.assertContains(due, "Owes Money")
        self.assertNotContains(due, "Paid Up")
        paid = self.client.get(reverse("fees:dues"), {"show": "paid"})
        self.assertContains(paid, "Paid Up")
        self.assertNotContains(paid, "Owes Money")

    def test_reminder_is_logged_and_opens_whatsapp(self):
        from apps.fees.models import FeeReminder

        self.client.force_login(self.office_user)
        response = self.client.post(reverse("fees:remind", args=[self.owing.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://wa.me/923001234567?text="))
        self.assertIn("3%2C000", response["Location"])
        reminder = FeeReminder.objects.get(student=self.owing)
        self.assertEqual(reminder.amount_due, Decimal("3000.00"))

    def test_reminder_needs_a_phone_and_rejects_offsite_next(self):
        from apps.fees.models import FeeReminder

        no_phone = self.paid_up
        FeeCharge.objects.create(
            student=no_phone, academic_year=self.year, description="Late fine",
            amount=Decimal("500.00"), due_date=self.today,
        )
        self.client.force_login(self.office_user)
        response = self.client.post(
            reverse("fees:remind", args=[no_phone.pk]), {"next": "https://evil.example/"}
        )
        self.assertEqual(response["Location"], reverse("fees:dues"))
        self.assertFalse(FeeReminder.objects.exists())

    def test_teacher_cannot_use_office_pages(self):
        self.client.force_login(self.teacher_user)
        for url in (
            reverse("fees:overview"),
            reverse("fees:staff"),
            reverse("fees:expenses"),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(reverse("fees:remind", args=[self.owing.pk])).status_code, 403)

    def test_office_pages_render(self):
        self.client.force_login(self.office_user)
        overview = self.client.get(reverse("fees:overview"))
        self.assertContains(overview, "Grade 5 A")
        self.assertEqual(overview.context["total_due"], Decimal("3000.00"))
        for url in (reverse("fees:staff"), reverse("fees:expenses"), reverse("fees:staff-create"), reverse("fees:expense-create")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_salary_can_be_paid_once_per_month(self):
        from apps.fees.models import Expense, StaffMember

        member = StaffMember.objects.create(name="Guard", designation="Guard", monthly_salary=Decimal("25000.00"))
        self.client.force_login(self.office_user)
        self.client.post(reverse("fees:staff-pay", args=[member.pk]))
        self.client.post(reverse("fees:staff-pay", args=[member.pk]))
        salary = Expense.objects.get(staff=member)
        self.assertEqual(salary.amount, Decimal("25000.00"))
        self.assertEqual(salary.salary_month, self.today.replace(day=1))
        self.assertEqual(salary.category, Expense.Category.SALARY)

    def test_expense_form_records_spending_but_not_salaries(self):
        from apps.fees.forms import ExpenseForm
        from apps.fees.models import Expense

        self.assertNotIn("salary", dict(ExpenseForm().fields["category"].choices))
        self.client.force_login(self.office_user)
        self.client.post(
            reverse("fees:expense-create"),
            {"category": "utilities", "description": "Electricity", "amount": "1500", "date": self.today.isoformat()},
        )
        expense = Expense.objects.get(description="Electricity")
        self.assertEqual(expense.recorded_by, self.office_user)
        overview = self.client.get(reverse("fees:overview"))
        self.assertEqual(overview.context["money"]["spent"], Decimal("1500.00"))
        self.assertEqual(overview.context["money"]["net"], Decimal("1500.00"))


class MonthlyFeeAndReceiptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import date, timedelta

        from apps.academics.models import Classroom, Enrollment

        cls.today = timezone.localdate()
        cls.year = AcademicYear.objects.create(
            name="Fee year", start_date=cls.today - timedelta(days=100),
            end_date=cls.today + timedelta(days=200), is_active=True,
        )
        cls.class_a = Classroom.objects.create(name="Grade 1", section="A", academic_year=cls.year)
        cls.class_b = Classroom.objects.create(name="Grade 2", section="A", academic_year=cls.year)
        cls.students = []
        for number, classroom in enumerate((cls.class_a, cls.class_a, cls.class_b), start=1):
            student = Student.objects.create(admission_number=f"M-{number}", first_name="Kid", last_name=str(number))
            Enrollment.objects.create(student=student, classroom=classroom, academic_year=cls.year)
            cls.students.append(student)
        cls.month = date(cls.today.year, cls.today.month, 1)
        cls.office_user = get_user_model().objects.create_user(username="office-month", role="office")

    def test_generate_bills_each_student_once_per_month(self):
        from apps.fees.services import generate_monthly_fees

        created, skipped, total = generate_monthly_fees(
            self.month, 10, {self.class_a.pk: Decimal("2500.00")}, self.office_user
        )
        self.assertEqual((created, skipped, total), (2, 0, Decimal("5000.00")))
        self.assertFalse(FeeCharge.objects.filter(student=self.students[2]).exists())

        created, skipped, _ = generate_monthly_fees(
            self.month, 10, {self.class_a.pk: Decimal("2500.00"), self.class_b.pk: Decimal("3000.00")}, self.office_user
        )
        self.assertEqual((created, skipped), (1, 2))
        charge = FeeCharge.objects.get(student=self.students[2])
        self.assertEqual(charge.amount, Decimal("3000.00"))
        self.assertEqual(charge.due_date, self.month.replace(day=10))
        self.assertEqual(charge.category, FeeCharge.Category.MONTHLY)

    def test_generate_page_validates_and_creates(self):
        self.client.force_login(self.office_user)
        response = self.client.post(
            reverse("fees:generate"),
            {"month": self.month.strftime("%Y-%m"), "due_day": "40", f"amount_{self.class_a.pk}": "abc"},
        )
        self.assertContains(response, "Due day must be a number from 1 to 28.")
        self.assertContains(response, "Enter a valid fee for Grade 1 A.")
        self.assertFalse(FeeCharge.objects.exists())

        response = self.client.post(
            reverse("fees:generate"),
            {"month": self.month.strftime("%Y-%m"), "due_day": "5", f"amount_{self.class_a.pk}": "2,000"},
        )
        self.assertRedirects(response, reverse("fees:dues"), fetch_redirect_response=False)
        self.assertEqual(FeeCharge.objects.filter(amount=Decimal("2000.00")).count(), 2)

    def test_receipt_shows_amount_in_words_two_copies_and_balance(self):
        FeeCharge.objects.create(
            student=self.students[0], academic_year=self.year, description="Fee",
            amount=Decimal("5000.00"), due_date=self.today,
        )
        payment = FeePayment.objects.create(
            student=self.students[0], academic_year=self.year, amount=Decimal("3500.00"),
            payment_date=self.today, method=FeePayment.Method.CASH,
        )
        self.client.force_login(self.office_user)
        response = self.client.get(reverse("fees:receipt", args=[payment.pk]))
        self.assertContains(response, "Three Thousand Five Hundred Rupees Only", count=2)
        self.assertContains(response, "Parent copy")
        self.assertContains(response, "School copy")
        self.assertContains(response, "Grade 1 A")
        self.assertEqual(response.context["balance_due"], Decimal("1500.00"))

    def test_rupees_in_words_uses_lakh_and_crore(self):
        from apps.fees.templatetags.fee_extras import rupees_words

        self.assertEqual(rupees_words("150000"), "One Lakh Fifty Thousand Rupees Only")
        self.assertEqual(rupees_words("10000000"), "One Crore Rupees Only")
        self.assertEqual(rupees_words("99.50"), "Ninety Nine Rupees and Fifty Paisa Only")
