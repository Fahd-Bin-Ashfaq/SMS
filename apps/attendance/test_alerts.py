from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TeacherAssignment
from apps.attendance.models import AbsenceAlert, AttendanceRecord
from apps.student_portal.models import Notification

User = get_user_model()


class AlertsAndNoticesTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        year = AcademicYear.objects.create(
            name="Alert year", start_date=self.today - timedelta(days=60), end_date=self.today + timedelta(days=200), is_active=True
        )
        self.mine = Classroom.objects.create(name="Grade 3", section="A", academic_year=year)
        self.other = Classroom.objects.create(name="Grade 3", section="B", academic_year=year)
        self.teacher = User.objects.create_user(username="alert-teacher", role="teacher")
        TeacherAssignment.objects.create(
            teacher=Teacher.objects.create(user=self.teacher), classroom=self.mine, subject=Subject.objects.create(name="Art", code="ART")
        )
        recorder = User.objects.create_user(username="recorder", role="principal")
        self.records = {}
        for classroom, name, phone, status in (
            (self.mine, "Absent Kid", "0300-5556667", "absent"),
            (self.mine, "Here Kid", "0300-1111111", "present"),
            (self.other, "Other Kid", "0300-2222222", "absent"),
        ):
            student = Student.objects.create(admission_number=name, first_name=name.split()[0], last_name="Kid", guardian_phone=phone)
            enrollment = Enrollment.objects.create(student=student, classroom=classroom, academic_year=year)
            self.records[name] = AttendanceRecord.objects.create(
                enrollment=enrollment, date=self.today, status=status, recorded_by=recorder
            )

    def test_teacher_sees_only_absences_in_own_classes_and_sends_alert(self):
        self.client.force_login(self.teacher)
        page = self.client.get(reverse("attendance:absence-alerts"))
        self.assertEqual([row["student"].first_name for row in page.context["rows"]], ["Absent"])
        response = self.client.post(reverse("attendance:send-absence-alert", args=[self.records["Absent Kid"].pk]))
        self.assertTrue(response["Location"].startswith("https://wa.me/923005556667?text="))
        self.assertEqual(AbsenceAlert.objects.get().sent_by, self.teacher)
        denied = self.client.post(reverse("attendance:send-absence-alert", args=[self.records["Other Kid"].pk]))
        self.assertEqual(denied.status_code, 403)

    def test_office_sees_all_and_parents_cannot(self):
        office = User.objects.create_user(username="alert-office", role="office")
        self.client.force_login(office)
        page = self.client.get(reverse("attendance:absence-alerts"))
        self.assertEqual(len(page.context["rows"]), 2)
        self.client.force_login(User.objects.create_user(username="alert-parent", role="parent"))
        self.assertEqual(self.client.get(reverse("attendance:absence-alerts")).status_code, 403)

    def test_notice_board_rules(self):
        self.client.force_login(self.teacher)
        self.client.post(reverse("student_portal:notices"), {"title": "Test", "message": "Bring colours", "classroom": self.mine.pk})
        self.assertEqual(Notification.objects.get().classroom, self.mine)
        self.client.post(reverse("student_portal:notices"), {"title": "Bad", "message": "x", "classroom": self.other.pk})
        self.client.post(reverse("student_portal:notices"), {"title": "All", "message": "x", "classroom": ""})
        self.assertEqual(Notification.objects.count(), 1)

        principal = User.objects.create_user(username="notice-principal", role="principal")
        self.client.force_login(principal)
        self.client.post(reverse("student_portal:notices"), {"title": "Holiday", "message": "School closed Monday", "classroom": ""})
        holiday = Notification.objects.get(title="Holiday")
        self.assertIsNone(holiday.classroom)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(reverse("student_portal:notice_delete", args=[holiday.pk])).status_code, 403)
        self.client.force_login(principal)
        self.client.post(reverse("student_portal:notice_delete", args=[holiday.pk]))
        self.assertFalse(Notification.objects.filter(title="Holiday").exists())
