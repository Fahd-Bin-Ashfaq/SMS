from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.fees.models import StaffMember

from .models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TeacherAssignment

User = get_user_model()


class PeopleFixture(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="People year", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30), is_active=True
        )
        self.class_a = Classroom.objects.create(name="Grade 5", section="A", academic_year=self.year)
        self.class_b = Classroom.objects.create(name="Grade 5", section="B", academic_year=self.year)
        self.math = Subject.objects.create(name="Mathematics", code="M-P")
        self.urdu = Subject.objects.create(name="Urdu", code="U-P")
        self.principal = User.objects.create_user(username="principal-people", role="principal")
        self.office = User.objects.create_user(username="office-people", role="office")


class AddStudentTests(PeopleFixture):
    def _post(self, **extra):
        data = {
            "admission_number": "N-1", "first_name": "New", "last_name": "Pupil",
            "classroom": self.class_a.pk, "guardian_phone": "0301-2223334", "is_active": "on",
        }
        data.update(extra)
        return self.client.post(reverse("academics:student_create"), data)

    def test_new_student_is_placed_in_the_chosen_class(self):
        self.client.force_login(self.office)
        self._post()
        student = Student.objects.get(admission_number="N-1")
        enrollment = student.enrollments.get()
        self.assertEqual((enrollment.classroom, enrollment.academic_year), (self.class_a, self.year))
        self.assertIsNone(student.user)

    def test_class_is_required(self):
        self.client.force_login(self.office)
        response = self._post(classroom="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Student.objects.exists())

    def test_editing_moves_the_student_to_another_class(self):
        self.client.force_login(self.office)
        self._post()
        student = Student.objects.get(admission_number="N-1")
        self.client.post(
            reverse("academics:student_update", args=[student.pk]),
            {"admission_number": "N-1", "first_name": "New", "last_name": "Pupil", "classroom": self.class_b.pk, "is_active": "on"},
        )
        self.assertEqual(student.enrollments.get().classroom, self.class_b)
        self.assertEqual(Enrollment.objects.count(), 1)

    def test_student_login_is_created_and_shown_once(self):
        self.client.force_login(self.office)
        self._post(create_login="on")
        student = Student.objects.get(admission_number="N-1")
        self.assertEqual((student.user.username, student.user.role), ("n-1", "student"))
        listing = self.client.get(reverse("academics:student_list"))
        credentials = listing.context["credentials"]
        self.assertTrue(student.user.check_password(credentials["password"]))
        self.assertIn("wa.me/923012223334", credentials["whatsapp"])
        self.assertIsNone(self.client.get(reverse("academics:student_list")).context["credentials"])

    def test_teacher_cannot_add_students(self):
        self.client.force_login(User.objects.create_user(username="t-add", role="teacher"))
        self._post()
        self.assertFalse(Student.objects.exists())


class TeacherManagementTests(PeopleFixture):
    def _create(self, **extra):
        data = {
            "first_name": "Hina", "last_name": "Shah", "phone": "0333-4445556", "monthly_salary": "52000",
            "class_teacher_of": self.class_a.pk,
            "assign": [f"{self.class_a.pk}-{self.math.pk}", f"{self.class_b.pk}-{self.urdu.pk}"],
        }
        data.update(extra)
        return self.client.post(reverse("academics:teacher_create"), data)

    def test_principal_creates_teacher_with_login_salary_and_classes(self):
        self.client.force_login(self.principal)
        self._create()
        teacher = Teacher.objects.get(user__username="03334445556")
        self.assertEqual(teacher.user.role, "teacher")
        self.assertEqual(
            set(TeacherAssignment.objects.filter(teacher=teacher).values_list("classroom_id", "subject_id")),
            {(self.class_a.pk, self.math.pk), (self.class_b.pk, self.urdu.pk)},
        )
        self.class_a.refresh_from_db()
        self.assertEqual(self.class_a.class_teacher, teacher)
        staff = StaffMember.objects.get(user=teacher.user)
        self.assertEqual((staff.designation, staff.monthly_salary, staff.phone), ("Teacher", Decimal("52000.00"), "0333-4445556"))
        credentials = self.client.get(reverse("academics:teacher_list")).context["credentials"]
        self.assertTrue(teacher.user.check_password(credentials["password"]))

    def test_editing_changes_classes_without_touching_the_password(self):
        self.client.force_login(self.principal)
        self._create()
        teacher = Teacher.objects.get(user__username="03334445556")
        teacher.user.set_password("keep-me")
        teacher.user.save()
        self.client.post(
            reverse("academics:teacher_update", args=[teacher.pk]),
            {"first_name": "Hina", "last_name": "Shah", "phone": "0333-4445556", "assign": [f"{self.class_b.pk}-{self.math.pk}"]},
        )
        self.assertEqual(
            list(TeacherAssignment.objects.filter(teacher=teacher).values_list("classroom_id", "subject_id")),
            [(self.class_b.pk, self.math.pk)],
        )
        self.class_a.refresh_from_db()
        self.assertIsNone(self.class_a.class_teacher)
        teacher.user.refresh_from_db()
        self.assertTrue(teacher.user.check_password("keep-me"))
        self.assertEqual(StaffMember.objects.get(user=teacher.user).monthly_salary, Decimal("52000.00"))

    def test_duplicate_username_is_rejected(self):
        self.client.force_login(self.principal)
        response = self._create(username="office-people")
        self.assertContains(response, "already used by someone else")
        self.assertFalse(Teacher.objects.exists())

    def test_left_school_blocks_sign_in_and_rejoin_restores_it(self):
        self.client.force_login(self.principal)
        self._create()
        teacher = Teacher.objects.get(user__username="03334445556")
        self.client.post(reverse("academics:teacher_action", args=[teacher.pk]), {"action": "deactivate"})
        teacher.user.refresh_from_db()
        self.assertFalse(teacher.user.is_active)
        self.assertFalse(StaffMember.objects.get(user=teacher.user).is_active)
        self.client.post(reverse("academics:teacher_action", args=[teacher.pk]), {"action": "activate"})
        teacher.user.refresh_from_db()
        self.assertTrue(teacher.user.is_active)

    def test_principal_can_add_a_subject(self):
        self.client.force_login(self.principal)
        self.client.post(reverse("academics:teacher_list"), {"subject-name": "Computer", "subject-code": "COMP"})
        self.assertTrue(Subject.objects.filter(code="COMP").exists())

    def test_only_principal_manages_teachers(self):
        for role in ("office", "teacher"):
            self.client.force_login(User.objects.create_user(username=f"no-{role}", role=role))
            self.assertEqual(self.client.get(reverse("academics:teacher_list")).status_code, 403)
            self.assertEqual(self._create().status_code, 403)
        self.assertFalse(Teacher.objects.exists())


class StaffLoginTests(PeopleFixture):
    def setUp(self):
        super().setUp()
        self.member = StaffMember.objects.create(
            name="Rashid Mehmood", designation="Accountant", phone="0345-1112223", monthly_salary=Decimal("40000")
        )

    def test_principal_gives_staff_an_office_login(self):
        self.client.force_login(self.principal)
        self.client.post(reverse("fees:staff-login", args=[self.member.pk]))
        self.member.refresh_from_db()
        self.assertEqual((self.member.user.username, self.member.user.role), ("03451112223", "office"))
        credentials = self.client.get(reverse("fees:staff")).context["credentials"]
        self.assertTrue(self.member.user.check_password(credentials["password"]))

    def test_office_cannot_create_logins(self):
        self.client.force_login(self.office)
        self.assertEqual(self.client.post(reverse("fees:staff-login", args=[self.member.pk])).status_code, 403)
        self.member.refresh_from_db()
        self.assertIsNone(self.member.user)

    def test_marking_staff_as_left_turns_off_their_login_only_for_principal(self):
        user = User.objects.create_user(username="rashid", role="office")
        self.member.user = user
        self.member.save()
        data = {"name": "Rashid Mehmood", "designation": "Accountant", "monthly_salary": "40000"}

        self.client.force_login(self.office)
        self.client.post(reverse("fees:staff-edit", args=[self.member.pk]), data)
        user.refresh_from_db()
        self.assertTrue(user.is_active)

        self.client.force_login(self.principal)
        self.client.post(reverse("fees:staff-edit", args=[self.member.pk]), data)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
