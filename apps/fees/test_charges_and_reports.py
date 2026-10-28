from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student
from apps.fees.models import FeeCharge, FeeConcession, FeePayment
from apps.fees.services import apply_late_fees, bulk_charge, generate_monthly_fees, month_start

User = get_user_model()


class ChargesFixture(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.year = AcademicYear.objects.create(
            name="Charge year", start_date=self.today - timedelta(days=120),
            end_date=self.today + timedelta(days=200), is_active=True,
        )
        self.classroom = Classroom.objects.create(name="Grade 9", section="A", academic_year=self.year)
        self.students = []
        for number in range(1, 4):
            student = Student.objects.create(admission_number=f"X-{number}", first_name=f"Kid{number}", last_name="X")
            Enrollment.objects.create(student=student, classroom=self.classroom, academic_year=self.year)
            self.students.append(student)
        self.principal = User.objects.create_user(username="principal-charges", role="principal")
        self.office = User.objects.create_user(username="office-charges", role="office")


class ConcessionTests(ChargesFixture):
    def test_concession_lowers_or_waives_the_monthly_fee(self):
        FeeConcession.objects.create(student=self.students[0], percent=Decimal("50"), reason="Sibling")
        FeeConcession.objects.create(student=self.students[1], percent=Decimal("100"), reason="Staff child")
        created, skipped, total, waived = generate_monthly_fees(
            month_start(self.today), 10, {self.classroom.pk: Decimal("3000")}, self.office
        )
        self.assertEqual((created, skipped, waived, total), (2, 0, 1, Decimal("4500")))
        self.assertEqual(FeeCharge.objects.get(student=self.students[0]).amount, Decimal("1500"))
        self.assertFalse(FeeCharge.objects.filter(student=self.students[1]).exists())

    def test_only_principal_sets_a_concession(self):
        url = reverse("fees:concession", args=[self.students[0].pk])
        self.client.force_login(self.office)
        self.assertEqual(self.client.post(url, {"percent": "25", "reason": "Need"}).status_code, 403)
        self.client.force_login(self.principal)
        self.client.post(url, {"percent": "25", "reason": "Need"})
        concession = FeeConcession.objects.get(student=self.students[0])
        self.assertEqual((concession.percent, concession.approved_by), (Decimal("25"), self.principal))
        self.client.post(url, {"percent": "150", "reason": "Too much"})
        concession.refresh_from_db()
        self.assertEqual(concession.percent, Decimal("25"))
        self.client.post(url, {"action": "remove"})
        self.assertFalse(FeeConcession.objects.exists())


class BulkAndLateFeeTests(ChargesFixture):
    def test_bulk_charge_adds_once_per_student(self):
        due = self.today + timedelta(days=7)
        self.assertEqual(
            bulk_charge([self.classroom.pk], FeeCharge.Category.ANNUAL, "Annual fund", Decimal("2000"), due, self.office),
            (3, 0),
        )
        self.assertEqual(
            bulk_charge([self.classroom.pk], FeeCharge.Category.ANNUAL, "Annual fund", Decimal("2000"), due, self.office),
            (0, 3),
        )
        self.client.force_login(self.office)
        self.client.post(
            reverse("fees:bulk-charge"),
            {"classrooms": [self.classroom.pk], "category": "exam", "description": "Exam fee", "amount": "500", "due_date": due.isoformat()},
        )
        self.assertEqual(FeeCharge.objects.filter(category=FeeCharge.Category.EXAM).count(), 3)

    def test_late_fee_only_for_unpaid_overdue_students_once(self):
        month = month_start(self.today - timedelta(days=40))
        for student in self.students:
            FeeCharge.objects.create(
                student=student, academic_year=self.year, category=FeeCharge.Category.MONTHLY,
                description="Tuition", amount=Decimal("3000"), due_date=month.replace(day=10),
            )
        FeePayment.objects.create(
            student=self.students[0], academic_year=self.year, amount=Decimal("3000"),
            payment_date=self.today, method=FeePayment.Method.CASH,
        )
        self.assertEqual(apply_late_fees(month, Decimal("200"), self.today, self.office), (2, 0))
        self.assertEqual(apply_late_fees(month, Decimal("200"), self.today, self.office), (0, 2))
        fined = set(FeeCharge.objects.filter(category=FeeCharge.Category.LATE_FEE).values_list("student_id", flat=True))
        self.assertEqual(fined, {self.students[1].pk, self.students[2].pk})

    def test_late_fee_is_not_charged_before_the_due_date(self):
        month = month_start(self.today)
        FeeCharge.objects.create(
            student=self.students[0], academic_year=self.year, category=FeeCharge.Category.MONTHLY,
            description="Tuition", amount=Decimal("3000"), due_date=self.today,
        )
        self.assertEqual(apply_late_fees(month, Decimal("200"), self.today, self.office), (0, 0))


class DailyReportTests(ChargesFixture):
    def test_daily_report_totals_by_method(self):
        for amount, method in (("1000", FeePayment.Method.CASH), ("2500", FeePayment.Method.CASH), ("700", FeePayment.Method.BANK_TRANSFER)):
            FeePayment.objects.create(
                student=self.students[0], academic_year=self.year, amount=Decimal(amount),
                payment_date=self.today, method=method, received_by=self.office,
            )
        FeePayment.objects.create(
            student=self.students[1], academic_year=self.year, amount=Decimal("9999"),
            payment_date=self.today - timedelta(days=1), method=FeePayment.Method.CASH,
        )
        self.client.force_login(self.office)
        response = self.client.get(reverse("fees:daily-report"))
        self.assertEqual(response.context["collected"], Decimal("4200"))
        self.assertEqual(dict(response.context["by_method"]), {"Cash": Decimal("3500"), "Bank transfer": Decimal("700")})
        yesterday = self.client.get(reverse("fees:daily-report"), {"date": (self.today - timedelta(days=1)).isoformat()})
        self.assertEqual(yesterday.context["collected"], Decimal("9999"))

    def test_pages_render_and_teachers_are_blocked(self):
        self.client.force_login(self.office)
        for name in ("fees:bulk-charge", "fees:late-fees", "fees:daily-report"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("fees:student-account", args=[self.students[0].pk])).status_code, 200)
        self.client.force_login(User.objects.create_user(username="t-charges", role="teacher"))
        for name in ("fees:bulk-charge", "fees:late-fees", "fees:daily-report"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
