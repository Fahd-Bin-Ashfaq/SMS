from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.academics.models import AcademicYear, Classroom, Subject, Teacher, TeacherAssignment
from apps.homework.forms import HomeworkForm
from apps.homework.models import Homework

User = get_user_model()


class HomeworkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
        )
        cls.classroom = Classroom.objects.create(
            name="Grade 5", section="A", academic_year=cls.year
        )
        cls.other_classroom = Classroom.objects.create(
            name="Grade 5", section="B", academic_year=cls.year
        )
        cls.math = Subject.objects.create(name="Mathematics", code="MATH")
        cls.science = Subject.objects.create(name="Science", code="SCI")
        cls.teacher_user = User.objects.create_user(
            username="teacher", password="Valid-password-123", role="teacher"
        )
        cls.other_teacher_user = User.objects.create_user(
            username="other-teacher", password="Valid-password-123", role="teacher"
        )
        cls.principal = User.objects.create_user(
            username="principal", password="Valid-password-123", role="principal"
        )
        cls.office_user = User.objects.create_user(
            username="office", password="Valid-password-123", role="office"
        )
        teacher = Teacher.objects.create(user=cls.teacher_user)
        other_teacher = Teacher.objects.create(user=cls.other_teacher_user)
        TeacherAssignment.objects.create(
            teacher=teacher, classroom=cls.classroom, subject=cls.math
        )
        TeacherAssignment.objects.create(
            teacher=teacher, classroom=cls.other_classroom, subject=cls.science
        )
        TeacherAssignment.objects.create(
            teacher=other_teacher, classroom=cls.classroom, subject=cls.science
        )
        cls.homework = Homework.objects.create(
            classroom=cls.classroom,
            subject=cls.math,
            assigned_by=cls.teacher_user,
            title="Fractions",
            assigned_date=date(2026, 10, 20),
            due_date=date(2026, 10, 23),
        )

    def test_model_rejects_due_date_before_assigned_date(self):
        homework = Homework(
            classroom=self.classroom,
            subject=self.math,
            assigned_by=self.teacher_user,
            title="Invalid dates",
            assigned_date=date(2026, 10, 23),
            due_date=date(2026, 10, 22),
        )

        with self.assertRaises(ValidationError) as error:
            homework.full_clean()

        self.assertIn("due_date", error.exception.message_dict)

    def test_model_rejects_unassigned_teacher_class_subject_pair(self):
        homework = Homework(
            classroom=self.classroom,
            subject=self.science,
            assigned_by=self.teacher_user,
            title="Unassigned subject",
            assigned_date=date(2026, 10, 20),
            due_date=date(2026, 10, 23),
        )

        with self.assertRaises(ValidationError) as error:
            homework.full_clean()

        self.assertIn("subject", error.exception.message_dict)

    def test_form_rejects_combination_of_individually_assigned_class_and_subject(self):
        form = HomeworkForm(
            data={
                "title": "Mismatch",
                "description": "",
                "classroom": self.other_classroom.pk,
                "subject": self.math.pk,
                "assigned_date": "2026-10-20",
                "due_date": "2026-10-23",
            },
            user=self.teacher_user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("subject", form.errors)

    def test_teacher_can_create_assigned_homework(self):
        self.client.force_login(self.teacher_user)

        response = self.client.post(
            reverse("homework:create"),
            {
                "title": "Read chapter",
                "description": "Complete the questions.",
                "classroom": self.classroom.pk,
                "subject": self.math.pk,
                "assigned_date": "2026-10-20",
                "due_date": "2026-10-24",
            },
        )

        self.assertRedirects(response, reverse("homework:index"))
        created = Homework.objects.get(title="Read chapter")
        self.assertEqual(created.assigned_by, self.teacher_user)

    def test_teacher_cannot_edit_another_teachers_homework(self):
        self.client.force_login(self.other_teacher_user)

        response = self.client.get(
            reverse("homework:edit", args=[self.homework.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_principal_and_office_can_review_but_not_assign(self):
        for user in (self.principal, self.office_user):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("homework:review"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.homework.title)
                self.assertEqual(
                    self.client.post(reverse("homework:create")).status_code, 403
                )

    def test_teacher_only_sees_homework_for_their_assigned_pair(self):
        Homework.objects.create(
            classroom=self.classroom,
            subject=self.science,
            assigned_by=self.other_teacher_user,
            title="Another teacher's subject",
            assigned_date=date(2026, 10, 20),
            due_date=date(2026, 10, 23),
        )
        self.client.force_login(self.teacher_user)

        response = self.client.get(reverse("homework:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.homework.title)
        self.assertNotContains(response, "Another teacher's subject")
