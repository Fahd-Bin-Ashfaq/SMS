from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student, Subject
from apps.assessments.models import Exam, ExamSubject, MarkChange, StudentMark


class StudentMarkValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
        )
        cls.classroom = Classroom.objects.create(
            name="Grade 7", section="A", academic_year=cls.year
        )
        cls.subject = Subject.objects.create(name="Mathematics", code="MATH")
        cls.student = Student.objects.create(
            admission_number="A-001", first_name="Ari", last_name="Learner"
        )
        Enrollment.objects.create(
            student=cls.student, classroom=cls.classroom, academic_year=cls.year
        )
        cls.exam = Exam.objects.create(
            academic_year=cls.year,
            classroom=cls.classroom,
            name="Term 1",
            date=date(2026, 12, 1),
        )
        cls.exam_subject = ExamSubject.objects.create(
            exam=cls.exam, subject=cls.subject, maximum_marks=Decimal("100")
        )

    def test_accepts_mark_within_maximum(self):
        mark = StudentMark.objects.create(
            exam=self.exam,
            student=self.student,
            subject=self.subject,
            marks_awarded=Decimal("87.50"),
        )
        self.assertEqual(mark.marks_awarded, Decimal("87.50"))
        self.assertIsNone(MarkChange.objects.get(mark=mark).previous_marks)

    def test_mark_updates_retain_previous_score(self):
        mark = StudentMark.objects.create(
            exam=self.exam,
            student=self.student,
            subject=self.subject,
            marks_awarded=Decimal("70"),
        )
        mark.marks_awarded = Decimal("75")
        mark.save()
        changes = list(mark.changes.order_by("changed_at"))
        self.assertEqual(changes[-1].previous_marks, Decimal("70"))
        self.assertEqual(changes[-1].new_marks, Decimal("75"))

    def test_exam_subject_is_unique_per_exam(self):
        with self.assertRaises(ValidationError):
            ExamSubject.objects.create(
                exam=self.exam,
                subject=self.subject,
                maximum_marks=Decimal("50"),
            )

    def test_student_mark_is_unique_per_exam_student_subject(self):
        StudentMark.objects.create(
            exam=self.exam,
            student=self.student,
            subject=self.subject,
            marks_awarded=Decimal("50"),
        )
        with self.assertRaises(ValidationError):
            StudentMark.objects.create(
                exam=self.exam,
                student=self.student,
                subject=self.subject,
                marks_awarded=Decimal("60"),
            )

    def test_rejects_mark_above_exam_subject_maximum(self):
        mark = StudentMark(
            exam=self.exam,
            student=self.student,
            subject=self.subject,
            marks_awarded=Decimal("100.01"),
        )
        with self.assertRaises(ValidationError) as error:
            mark.save()
        self.assertIn("marks_awarded", error.exception.message_dict)

    def test_rejects_negative_mark(self):
        mark = StudentMark(
            exam=self.exam,
            student=self.student,
            subject=self.subject,
            marks_awarded=Decimal("-0.01"),
        )
        with self.assertRaises(ValidationError) as error:
            mark.save()
        self.assertIn("marks_awarded", error.exception.message_dict)

    def test_rejects_student_not_enrolled_in_exam_class_and_year(self):
        other = Student.objects.create(
            admission_number="A-002", first_name="Sam", last_name="Unenrolled"
        )
        mark = StudentMark(
            exam=self.exam,
            student=other,
            subject=self.subject,
            marks_awarded=Decimal("50"),
        )
        with self.assertRaises(ValidationError) as error:
            mark.save()
        self.assertIn("student", error.exception.message_dict)

    def test_rejects_subject_not_configured_for_exam(self):
        other_subject = Subject.objects.create(name="Science", code="SCI")
        mark = StudentMark(
            exam=self.exam,
            student=self.student,
            subject=other_subject,
            marks_awarded=Decimal("50"),
        )
        with self.assertRaises(ValidationError) as error:
            mark.save()
        self.assertIn("subject", error.exception.message_dict)

    def test_exam_subject_maximum_must_be_positive(self):
        with self.assertRaises(ValidationError):
            ExamSubject.objects.create(
                exam=self.exam,
                subject=Subject.objects.create(name="Art", code="ART"),
                maximum_marks=Decimal("0"),
            )
