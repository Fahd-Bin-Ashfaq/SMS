from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.fees.models import Expense, SalarySlip, StaffAttendance, StaffMember
from apps.fees.services import advance_outstanding, salary_suggestion

User = get_user_model()


class SalaryAndStaffAttendanceTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.month = self.today.replace(day=1)
        self.member = StaffMember.objects.create(name="Bilal Guard", designation="Guard", monthly_salary=Decimal("30000"))
        self.office = User.objects.create_user(username="office-salary", role="office")
        self.client.force_login(self.office)

    def test_staff_attendance_is_saved_and_counted(self):
        self.client.post(
            reverse("fees:staff-attendance"),
            {"date": self.today.isoformat(), f"status_{self.member.pk}": "absent", f"note_{self.member.pk}": "Sick"},
        )
        record = StaffAttendance.objects.get(staff=self.member, date=self.today)
        self.assertEqual((record.status, record.note, record.marked_by), ("absent", "Sick", self.office))
        self.client.post(reverse("fees:staff-attendance"), {"date": self.today.isoformat(), f"status_{self.member.pk}": "leave"})
        self.assertEqual(StaffAttendance.objects.get(staff=self.member).status, "leave")
        page = self.client.get(reverse("fees:staff-attendance"))
        self.assertEqual(page.context["members"][0].month_leave, 1)

    def test_suggestion_deducts_absences_and_owed_advance(self):
        StaffAttendance.objects.create(staff=self.member, date=self.month, status=StaffAttendance.Status.ABSENT)
        self.client.post(reverse("fees:staff-advance", args=[self.member.pk]), {"amount": "5000"})
        self.assertEqual(advance_outstanding(self.member), Decimal("5000"))
        suggestion = salary_suggestion(self.member, self.month)
        self.assertEqual(suggestion["absent_days"], 1)
        self.assertEqual(suggestion["absence_deduction"], Decimal("1000"))
        self.assertEqual(suggestion["advance_recovered"], Decimal("5000"))

    def test_paying_salary_creates_slip_with_net_amount(self):
        self.client.post(reverse("fees:staff-advance", args=[self.member.pk]), {"amount": "5000"})
        response = self.client.post(
            reverse("fees:staff-pay", args=[self.member.pk]),
            {"basic": "30000", "allowance": "2000", "absent_days": "1", "absence_deduction": "1000",
             "advance_recovered": "3000", "other_deduction": "", "note": "Eid bonus"},
        )
        salary = Expense.objects.get(staff=self.member, category=Expense.Category.SALARY)
        self.assertRedirects(response, reverse("fees:salary-slip", args=[salary.pk]), fetch_redirect_response=False)
        self.assertEqual(salary.amount, Decimal("28000"))
        self.assertEqual(salary.slip.advance_recovered, Decimal("3000"))
        self.assertEqual(advance_outstanding(self.member), Decimal("2000"))
        slip_page = self.client.get(reverse("fees:salary-slip", args=[salary.pk]))
        self.assertContains(slip_page, "Twenty Eight Thousand Rupees Only")

        again = self.client.get(reverse("fees:staff-pay", args=[self.member.pk]))
        self.assertRedirects(again, reverse("fees:salary-slip", args=[salary.pk]), fetch_redirect_response=False)

    def test_cannot_recover_more_advance_than_owed_or_pay_nothing(self):
        response = self.client.post(
            reverse("fees:staff-pay", args=[self.member.pk]), {"basic": "30000", "advance_recovered": "100"}
        )
        self.assertContains(response, "of advance is still owed")
        response = self.client.post(
            reverse("fees:staff-pay", args=[self.member.pk]), {"basic": "1000", "other_deduction": "1000"}
        )
        self.assertContains(response, "must be more than zero")
        self.assertFalse(SalarySlip.objects.exists())

    def test_advances_and_salaries_stay_out_of_the_general_expense_form(self):
        from apps.fees.forms import ExpenseForm

        choices = dict(ExpenseForm().fields["category"].choices)
        self.assertNotIn("salary", choices)
        self.assertNotIn("advance", choices)

    def test_teachers_cannot_use_staff_tools(self):
        self.client.force_login(User.objects.create_user(username="t-salary", role="teacher"))
        self.assertEqual(self.client.get(reverse("fees:staff-attendance")).status_code, 403)
        self.assertEqual(self.client.get(reverse("fees:staff-pay", args=[self.member.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("fees:staff-advance", args=[self.member.pk]), {"amount": "1"}).status_code, 403)
