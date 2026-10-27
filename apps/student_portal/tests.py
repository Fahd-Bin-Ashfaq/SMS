from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    Classroom,
    Enrollment,
    Student,
    Subject,
    Teacher,
    TeacherAssignment,
    TimetableEntry,
)
from apps.academics.timetable import next_period
from apps.fees.models import FeeCharge, FeePayment
from apps.homework.models import Homework

from .models import Notification
from .services import fee_overview


class PortalFixture(TestCase):
    def setUp(self):
        User = get_user_model()
        today = timezone.localdate()
        self.year = AcademicYear.objects.create(
            name="Current",
            start_date=today - timedelta(days=90),
            end_date=today + timedelta(days=200),
            is_active=True,
        )
        self.classroom = Classroom.objects.create(name="Grade 6", section="A", academic_year=self.year)
        self.other_classroom = Classroom.objects.create(name="Grade 7", section="A", academic_year=self.year)
        self.subject = Subject.objects.create(name="Mathematics", code="MATH")

        self.class_teacher_user = User.objects.create_user(username="ct", role="teacher")
        self.class_teacher = Teacher.objects.create(user=self.class_teacher_user)
        self.other_teacher_user = User.objects.create_user(username="other", role="teacher")
        self.other_teacher = Teacher.objects.create(user=self.other_teacher_user)
        self.classroom.class_teacher = self.class_teacher
        self.classroom.save()
        for classroom in (self.classroom, self.other_classroom):
            TeacherAssignment.objects.create(teacher=self.class_teacher, classroom=classroom, subject=self.subject)
            TeacherAssignment.objects.create(teacher=self.other_teacher, classroom=classroom, subject=self.subject)

        self.student_user = User.objects.create_user(username="kid", role="student")
        self.student = Student.objects.create(
            user=self.student_user, admission_number="S-1", first_name="Ali", last_name="Khan"
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student, classroom=self.classroom, academic_year=self.year
        )
        self.principal = User.objects.create_user(username="boss", role="principal")


class StudentPortalAccessTests(PortalFixture):
    def test_every_page_renders_for_a_linked_student(self):
        self.client.force_login(self.student_user)
        for url in (
            "/portal/",
            "/portal/classroom/",
            "/portal/homework/",
            "/portal/study-guides/",
            "/portal/balance/",
            "/portal/id-card/",
            "/portal/profile/",
            "/portal/profile/edit/",
            "/portal/notifications/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_staff_are_sent_to_the_staff_dashboard(self):
        self.client.force_login(self.principal)
        self.assertRedirects(
            self.client.get("/portal/"), "/dashboard/", fetch_redirect_response=False
        )

    def test_student_without_a_record_sees_not_linked_page(self):
        user = get_user_model().objects.create_user(username="orphan", role="student")
        self.client.force_login(user)
        response = self.client.get("/portal/")
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "not linked", status_code=403)

    def test_notifications_only_show_own_class_and_school_wide(self):
        Notification.objects.create(title="For everyone", message="x")
        Notification.objects.create(title="For my class", message="x", classroom=self.classroom)
        Notification.objects.create(title="For another class", message="x", classroom=self.other_classroom)
        self.client.force_login(self.student_user)
        response = self.client.get("/portal/notifications/")
        self.assertContains(response, "For everyone")
        self.assertContains(response, "For my class")
        self.assertNotContains(response, "For another class")

    def test_homework_page_shows_own_class_split_into_due_and_past(self):
        today = timezone.localdate()
        common = {"subject": self.subject, "assigned_by": self.class_teacher_user, "assigned_date": today - timedelta(days=5)}
        due = Homework.objects.create(classroom=self.classroom, title="Due work", due_date=today + timedelta(days=2), **common)
        Homework.objects.create(classroom=self.classroom, title="Old work", due_date=today - timedelta(days=1), **common)
        other = Homework.objects.create(classroom=self.other_classroom, title="Other class work", due_date=today + timedelta(days=2), **common)
        self.client.force_login(self.student_user)
        response = self.client.get("/portal/homework/")
        self.assertEqual([item.title for item in response.context["upcoming"]], ["Due work"])
        self.assertEqual([item.title for item in response.context["past"]], ["Old work"])
        self.assertNotContains(response, "Other class work")
        self.assertEqual(response.context["due_homework"], 1)
        self.assertContains(response, f"/portal/homework/{due.pk}/")

        detail = self.client.get(f"/portal/homework/{due.pk}/")
        self.assertContains(detail, "Due work")
        self.assertContains(detail, "2 days left")
        self.assertEqual(self.client.get(f"/portal/homework/{other.pk}/").status_code, 404)

    def test_profile_edit_cannot_change_identity_fields(self):
        self.client.force_login(self.student_user)
        response = self.client.post(
            "/portal/profile/edit/",
            {"first_name": "Hacked", "admission_number": "X", "email": "ali@example.com", "phone": "123"},
        )
        self.assertRedirects(response, "/portal/profile/")
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, "Ali")
        self.assertEqual(self.student.admission_number, "S-1")
        self.assertEqual(self.student.email, "ali@example.com")


class TimetableTests(PortalFixture):
    def entry(self, **kwargs):
        values = {
            "classroom": self.classroom,
            "day": 0,
            "start_time": time(8, 0),
            "end_time": time(8, 40),
            "subject": self.subject,
            "teacher": self.class_teacher,
        }
        values.update(kwargs)
        return TimetableEntry(**values)

    def test_overlapping_periods_in_one_class_are_rejected(self):
        self.entry().save()
        with self.assertRaises(ValidationError):
            self.entry(start_time=time(8, 20), end_time=time(9, 0), teacher=self.other_teacher).full_clean()

    def test_teacher_cannot_be_in_two_classes_at_once(self):
        self.entry().save()
        with self.assertRaises(ValidationError):
            self.entry(classroom=self.other_classroom).full_clean()

    def test_class_teacher_and_principal_can_edit_but_other_teachers_cannot(self):
        url = f"/academics/timetable/{self.classroom.pk}/"
        data = {"day": 1, "start_time": "09:00", "end_time": "09:40", "subject": self.subject.pk, "teacher": self.class_teacher.pk}

        self.client.force_login(self.other_teacher_user)
        self.assertFalse(self.client.get(url).context["can_edit"])
        self.assertEqual(self.client.post(url, data).status_code, 403)

        self.client.force_login(self.class_teacher_user)
        self.assertRedirects(self.client.post(url, data), url)

        self.client.force_login(self.principal)
        data.update(day=2)
        self.assertRedirects(self.client.post(url, data), url)
        self.assertEqual(self.classroom.timetable_entries.count(), 2)

    def test_next_period_skips_finished_periods_and_breaks(self):
        monday = date(2026, 10, 19)
        self.entry(day=0, start_time=time(8, 0), end_time=time(8, 40)).save()
        TimetableEntry.objects.create(classroom=self.classroom, day=0, start_time=time(8, 40), end_time=time(9, 0), label="Break")
        later = self.entry(day=0, start_time=time(9, 0), end_time=time(9, 40))
        later.save()
        entry, when = next_period(self.classroom, datetime.combine(monday, time(8, 45)))
        self.assertEqual((entry, when), (later, monday))
        entry, when = next_period(self.classroom, datetime.combine(monday, time(10, 0)))
        self.assertEqual(when, monday + timedelta(days=7))


class FeeOverviewTests(PortalFixture):
    def charge(self, due, amount="3000"):
        return FeeCharge.objects.create(
            student=self.student,
            academic_year=self.year,
            description=f"Fee {due}",
            amount=Decimal(amount),
            due_date=due,
        )

    def test_payments_cover_oldest_months_first_and_future_months_are_upcoming(self):
        today = timezone.localdate()
        first = date(self.year.start_date.year, self.year.start_date.month, 10)
        second = date(first.year + first.month // 12, first.month % 12 + 1, 10)
        self.charge(first)
        self.charge(second)
        FeePayment.objects.create(student=self.student, academic_year=self.year, amount=Decimal("4000"))

        overview = fee_overview(self.student, self.year, today)
        statuses = [row["status"] for row in overview["months"]]
        self.assertEqual(statuses[:2], ["paid", "partial"])
        self.assertTrue(all(status == "upcoming" for status in statuses[2:]))
        self.assertEqual(overview["due_now"], Decimal("2000"))
        self.assertEqual(overview["paid"], Decimal("4000"))
        self.assertEqual(overview["year_total"], Decimal("3000") * len(overview["months"]))
