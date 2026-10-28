from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TeacherAssignment
from apps.homework.models import Homework, HomeworkCompletion

User = get_user_model()


class HomeworkCheckTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        year = AcademicYear.objects.create(
            name="HW year", start_date=today - timedelta(days=60), end_date=today + timedelta(days=200), is_active=True
        )
        self.classroom = Classroom.objects.create(name="Grade 4", section="A", academic_year=year)
        subject = Subject.objects.create(name="English", code="ENG-HW")
        self.teacher_user = User.objects.create_user(username="hw-teacher", role="teacher")
        TeacherAssignment.objects.create(
            teacher=Teacher.objects.create(user=self.teacher_user), classroom=self.classroom, subject=subject
        )
        self.done_student = Student.objects.create(admission_number="H-1", first_name="Done", last_name="Kid")
        self.lazy_student = Student.objects.create(admission_number="H-2", first_name="Lazy", last_name="Kid")
        self.student_user = User.objects.create_user(username="hw-student", role="student")
        self.lazy_student.user = self.student_user
        self.lazy_student.save()
        for student in (self.done_student, self.lazy_student):
            Enrollment.objects.create(student=student, classroom=self.classroom, academic_year=year)
        self.homework = Homework.objects.create(
            classroom=self.classroom, subject=subject, assigned_by=self.teacher_user, title="Essay",
            assigned_date=today, due_date=today + timedelta(days=2),
        )

    def test_teacher_marks_done_and_not_done(self):
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse("homework:check", args=[self.homework.pk]))
        self.assertEqual(len(page.context["students"]), 2)
        self.client.post(reverse("homework:check", args=[self.homework.pk]), {"done": [str(self.done_student.pk)]})
        status = dict(HomeworkCompletion.objects.values_list("student_id", "is_done"))
        self.assertEqual(status, {self.done_student.pk: True, self.lazy_student.pk: False})

        listing = self.client.get(reverse("homework:index"))
        item = listing.context["homework_list"][0]
        self.assertEqual((item.done_count, item.checked_count), (1, 2))

    def test_other_teacher_and_office_cannot_check(self):
        for username, role in (("other-hw", "teacher"), ("office-hw", "office")):
            self.client.force_login(User.objects.create_user(username=username, role=role))
            response = self.client.post(reverse("homework:check", args=[self.homework.pk]), {"done": []})
            self.assertEqual(response.status_code, 403)
        self.assertFalse(HomeworkCompletion.objects.exists())

    def test_student_sees_the_teachers_check(self):
        HomeworkCompletion.objects.create(homework=self.homework, student=self.lazy_student, is_done=False)
        self.client.force_login(self.student_user)
        listing = self.client.get("/portal/homework/")
        self.assertContains(listing, "Checked: not done")
        detail = self.client.get(f"/portal/homework/{self.homework.pk}/")
        self.assertContains(detail, "please complete and show your teacher")
