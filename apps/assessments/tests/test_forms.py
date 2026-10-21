from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.academics.models import (
    AcademicYear,
    Classroom,
    Enrollment,
    Student,
    Subject,
    Teacher,
    TeacherAssignment,
)
from apps.assessments.forms import MarkEntryForm
from apps.assessments.models import Exam, ExamSubject, StudentMark


class MarkEntryFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="teacher", password="test-password", role="teacher"
        )
        cls.teacher = Teacher.objects.create(user=cls.user)
        cls.year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
        )
        cls.classroom = Classroom.objects.create(
            name="Grade 8", section="A", academic_year=cls.year
        )
        cls.subject = Subject.objects.create(name="English", code="ENG")
        TeacherAssignment.objects.create(
            teacher=cls.teacher, classroom=cls.classroom, subject=cls.subject
        )
        cls.student = Student.objects.create(
            admission_number="E-001", first_name="Taylor", last_name="Student"
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, classroom=cls.classroom, academic_year=cls.year
        )
        cls.exam = Exam.objects.create(
            academic_year=cls.year, classroom=cls.classroom, name="Final"
        )
        cls.exam_subject = ExamSubject.objects.create(
            exam=cls.exam, subject=cls.subject, maximum_marks=Decimal("80")
        )

    def payload(self, marks="72.50"):
        return {
            "exam": self.exam.pk,
            "exam_subject": self.exam_subject.pk,
            "enrollment": self.enrollment.pk,
            "marks_awarded": marks,
        }

    def test_assigned_teacher_can_submit_marks(self):
        form = MarkEntryForm(self.payload(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.marks_awarded, Decimal("72.50"))
        self.assertEqual(StudentMark.objects.count(), 1)

    def test_marks_above_maximum_have_explicit_error(self):
        form = MarkEntryForm(self.payload("80.01"), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("maximum", str(form.errors["marks_awarded"]))

    def test_teacher_cannot_submit_unassigned_subject(self):
        other = Subject.objects.create(name="History", code="HIST")
        unassigned_exam_subject = ExamSubject.objects.create(
            exam=self.exam, subject=other, maximum_marks=Decimal("100")
        )
        payload = self.payload()
        payload["exam_subject"] = unassigned_exam_subject.pk
        form = MarkEntryForm(payload, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("exam_subject", form.errors)
