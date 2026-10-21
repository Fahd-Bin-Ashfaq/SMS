from datetime import timedelta

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
)
from .models import AttendanceCorrection, AttendanceRecord
from .views import _can_access_context


class AttendanceRecordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.valid_date = today - timedelta(days=1)
        cls.future_date = today + timedelta(days=1)
        user_model = get_user_model()
        cls.teacher_user = user_model.objects.create_user(
            username="teacher",
            password="test-password",
            role="teacher",
        )
        cls.other_teacher_user = user_model.objects.create_user(
            username="other-teacher",
            password="test-password",
            role="teacher",
        )
        cls.year = AcademicYear.objects.create(
            name=f"{today.year}-{today.year + 1}",
            start_date=today - timedelta(days=180),
            end_date=today + timedelta(days=180),
            is_active=True,
        )
        cls.classroom = Classroom.objects.create(
            name="Grade 1",
            section="A",
            academic_year=cls.year,
        )
        cls.other_classroom = Classroom.objects.create(
            name="Grade 1",
            section="B",
            academic_year=cls.year,
        )
        cls.subject = Subject.objects.create(name="Mathematics", code="MATH")
        teacher = Teacher.objects.create(user=cls.teacher_user)
        TeacherAssignment.objects.create(
            teacher=teacher,
            classroom=cls.classroom,
            subject=cls.subject,
        )
        student = Student.objects.create(
            admission_number="STU-001",
            first_name="Ada",
            last_name="Lovelace",
        )
        cls.enrollment = Enrollment.objects.create(
            student=student,
            classroom=cls.classroom,
            academic_year=cls.year,
            status=Enrollment.Status.ACTIVE,
        )

    def test_status_correction_creates_audit_history(self):
        record = AttendanceRecord.objects.create(
            enrollment=self.enrollment,
            date=self.valid_date,
            status=AttendanceRecord.Status.PRESENT,
            recorded_by=self.teacher_user,
        )
        record.status = AttendanceRecord.Status.LATE
        record._changed_by = self.teacher_user
        record._correction_reason = "Student arrived after roll call."
        record.save()

        correction = AttendanceCorrection.objects.get(attendance=record)
        self.assertEqual(correction.previous_status, AttendanceRecord.Status.PRESENT)
        self.assertEqual(correction.new_status, AttendanceRecord.Status.LATE)
        self.assertEqual(correction.changed_by, self.teacher_user)
        self.assertEqual(correction.reason, "Student arrived after roll call.")

    def test_duplicate_enrollment_and_date_is_rejected(self):
        AttendanceRecord.objects.create(
            enrollment=self.enrollment,
            date=self.valid_date,
            status=AttendanceRecord.Status.PRESENT,
            recorded_by=self.teacher_user,
        )
        with self.assertRaises(ValidationError):
            AttendanceRecord.objects.create(
                enrollment=self.enrollment,
                date=self.valid_date,
                status=AttendanceRecord.Status.ABSENT,
                recorded_by=self.teacher_user,
            )

    def test_future_and_inactive_enrollments_are_rejected(self):
        record = AttendanceRecord(
            enrollment=self.enrollment,
            date=self.future_date,
            status=AttendanceRecord.Status.PRESENT,
            recorded_by=self.teacher_user,
        )
        with self.assertRaises(ValidationError):
            record.full_clean()

        self.enrollment.status = Enrollment.Status.INACTIVE
        self.enrollment.save()
        record.date = self.valid_date
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_teacher_access_requires_assigned_classroom_and_subject(self):
        self.assertTrue(
            _can_access_context(self.teacher_user, self.classroom, self.subject)
        )
        self.assertFalse(
            _can_access_context(self.other_teacher_user, self.classroom, self.subject)
        )
        self.assertFalse(
            _can_access_context(self.teacher_user, self.other_classroom, self.subject)
        )
