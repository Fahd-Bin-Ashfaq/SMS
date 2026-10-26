from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, TestCase

from . import views


class DashboardAccessTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_user_without_dashboard_role_is_forbidden(self):
        request = self.factory.get("/dashboard/")
        request.user = SimpleNamespace(is_authenticated=True, role="visitor")
        with self.assertRaises(PermissionDenied):
            views.index.__wrapped__(request)

    def test_anonymous_user_is_redirected_to_login(self):
        request = self.factory.get("/dashboard/")
        request.user = AnonymousUser()
        response = views.index(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts/login/?next=/dashboard/")

    @patch("apps.dashboard.views.build_dashboard_context")
    def test_office_dashboard_does_not_require_academic_or_exam_data(self, build_context):
        build_context.return_value = {
            "role": "office",
            "today": __import__("datetime").date.today(),
            "active_students": 0,
            "active_teachers": 0,
            "attendance": {"present": 0, "absent": 0, "late": 0, "total": 0},
            "upcoming_homework": [],
            "recent_exams": [],
            "fee_charged": 0,
            "fee_paid": 0,
            "fee_balance": 0,
            "class_count": 0,
        }
        request = self.factory.get("/dashboard/")
        request.user = get_user_model()(role="office")
        response = views.index.__wrapped__(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Recent exams")


class DashboardEmptyDataTests(TestCase):
    def test_empty_school_database_produces_empty_summary(self):
        user = get_user_model().objects.create_user(username="principal", role="principal")
        context = views.build_dashboard_context(user)
        self.assertEqual(context["active_students"], 0)
        self.assertEqual(context["active_teachers"], 0)
        self.assertEqual(context["attendance"]["total"], 0)
        self.assertEqual(context["upcoming_homework"], [])
        self.assertEqual(context["recent_exams"], [])
        self.assertEqual(context["fee_balance"], 0)

    def test_teacher_with_no_assignments_sees_no_students_or_attendance(self):
        user = get_user_model().objects.create_user(username="teacher", role="teacher")
        context = views.build_dashboard_context(user)
        self.assertEqual(context["active_students"], 0)
        self.assertEqual(context["class_count"], 0)
        self.assertEqual(context["attendance"]["total"], 0)
        self.assertEqual(context["fee_balance"], 0)

    def test_student_dashboard_only_includes_their_linked_profile_and_attendance(self):
        from datetime import date

        from apps.academics.models import AcademicYear, Classroom, Enrollment, Student
        from apps.attendance.models import AttendanceRecord

        User = get_user_model()
        student_user = User.objects.create_user(username="student", role="student")
        recorder = User.objects.create_user(username="principal", role="principal")
        year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 8, 1),
            end_date=date(2027, 6, 30),
            is_active=True,
        )
        classroom = Classroom.objects.create(name="Grade 6", section="A", academic_year=year)
        own_student = Student.objects.create(
            user=student_user,
            admission_number="DEMO-001",
            first_name="Demo",
            last_name="Student",
        )
        other_student = Student.objects.create(
            admission_number="DEMO-002",
            first_name="Other",
            last_name="Student",
        )
        own_enrollment = Enrollment.objects.create(
            student=own_student, classroom=classroom, academic_year=year
        )
        AttendanceRecord.objects.create(
            enrollment=own_enrollment,
            date=__import__("django.utils.timezone", fromlist=["localdate"]).localdate(),
            status=AttendanceRecord.Status.PRESENT,
            recorded_by=recorder,
        )
        Enrollment.objects.create(
            student=other_student, classroom=classroom, academic_year=year
        )

        context = views.build_dashboard_context(student_user)
        self.assertEqual(context["active_students"], 1)
        self.assertEqual(context["attendance"]["total"], 1)

        self.client.force_login(student_user)
        response = self.client.get("/dashboard/")
        self.assertRedirects(response, "/portal/")
