from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TeacherAssignment


User = get_user_model()


class AcademicModelTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="2026-2027", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30)
        )
        self.classroom = Classroom.objects.create(
            name="Grade 6", section="A", academic_year=self.year
        )
        self.student = Student.objects.create(
            admission_number="S-001", first_name="Ari", last_name="Example"
        )

    def test_academic_year_rejects_end_before_start(self):
        year = AcademicYear(
            name="Invalid", start_date=date(2027, 1, 1), end_date=date(2026, 1, 1)
        )
        with self.assertRaises(ValidationError):
            year.full_clean()

    def test_enrollment_rejects_classroom_year_mismatch(self):
        other_year = AcademicYear.objects.create(
            name="2027-2028", start_date=date(2027, 8, 1), end_date=date(2028, 6, 30)
        )
        enrollment = Enrollment(
            student=self.student,
            classroom=self.classroom,
            academic_year=other_year,
        )
        with self.assertRaises(ValidationError):
            enrollment.full_clean()

    def test_student_cannot_have_duplicate_enrollment_in_year(self):
        Enrollment.objects.create(
            student=self.student, classroom=self.classroom, academic_year=self.year
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Enrollment.objects.create(
                student=self.student, classroom=self.classroom, academic_year=self.year
            )

    def test_teacher_assignment_is_unique(self):
        user = User.objects.create_user(
            username="teacher", password="test-password", role="teacher"
        )
        teacher = Teacher.objects.create(user=user)
        subject = Subject.objects.create(name="Mathematics", code="MATH")
        TeacherAssignment.objects.create(
            teacher=teacher, classroom=self.classroom, subject=subject
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeacherAssignment.objects.create(
                teacher=teacher, classroom=self.classroom, subject=subject
            )


class AcademicPermissionTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="2026-2027", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30)
        )
        self.assigned_class = Classroom.objects.create(
            name="Grade 6", section="A", academic_year=self.year
        )
        self.other_class = Classroom.objects.create(
            name="Grade 7", section="B", academic_year=self.year
        )
        self.student = Student.objects.create(
            admission_number="S-001", first_name="Ari", last_name="Example"
        )
        Enrollment.objects.create(
            student=self.student,
            classroom=self.assigned_class,
            academic_year=self.year,
        )
        self.teacher_user = User.objects.create_user(
            username="teacher", password="test-password", role="teacher"
        )
        teacher = Teacher.objects.create(user=self.teacher_user)
        subject = Subject.objects.create(name="Mathematics", code="MATH")
        TeacherAssignment.objects.create(
            teacher=teacher, classroom=self.assigned_class, subject=subject
        )

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username, password="test-password", role=role
        )

    def test_teacher_sees_only_assigned_classes_and_enrolled_students(self):
        self.client.force_login(self.teacher_user)
        classes = self.client.get(reverse("academics:classroom_list"))
        students = self.client.get(reverse("academics:student_list"))
        self.assertContains(classes, "Grade 6")
        self.assertNotContains(classes, "Grade 7")
        self.assertContains(students, "S-001")
        self.assertNotContains(students, "Edit")

    def test_teacher_cannot_access_management_actions(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse("academics:student_create"), {
            "admission_number": "S-002",
            "first_name": "New",
            "last_name": "Student",
            "is_active": "on",
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Student.objects.filter(admission_number="S-002").exists())

    def test_office_can_create_student(self):
        self.client.force_login(self.make_user("office", "office"))
        response = self.client.post(
            reverse("academics:student_create"),
            {
                "admission_number": "S-002",
                "first_name": "New",
                "last_name": "Student",
                "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("academics:student_list"))
        self.assertTrue(Student.objects.filter(admission_number="S-002").exists())

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("academics:student_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login", response.url)
