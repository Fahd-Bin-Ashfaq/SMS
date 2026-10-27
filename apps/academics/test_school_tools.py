import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import AcademicYear, Classroom, Enrollment, Student
from .promotion import promote

User = get_user_model()


def _upload(name, content):
    return SimpleUploadedFile(name, content.encode("utf-8") if isinstance(content, str) else content)


class StudentImportTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="Import year", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30), is_active=True
        )
        self.grade6 = Classroom.objects.create(name="Grade 6", section="A", academic_year=self.year)
        self.client.force_login(User.objects.create_user(username="office-import", role="office"))

    def test_csv_import_creates_students_and_enrollments(self):
        Student.objects.create(admission_number="S-2", first_name="Old", last_name="Name")
        csv_text = (
            "Admission No,First Name,Last Name,Class,Section,Father Name,Mobile,DOB,Gender\n"
            "S-1,Ali,Khan,grade 6,a,Imran Khan,0300-1234567,15/03/2014,M\n"
            "S-2,Sara Ahmed,,Grade 6,A,,,,Female\n"
        )
        response = self.client.post(reverse("academics:student_import"), {"file": _upload("students.csv", csv_text)})
        self.assertRedirects(response, reverse("academics:student_list"), fetch_redirect_response=False)
        ali = Student.objects.get(admission_number="S-1")
        self.assertEqual(
            (ali.guardian_name, ali.guardian_phone, ali.date_of_birth, ali.gender),
            ("Imran Khan", "0300-1234567", date(2014, 3, 15), Student.Gender.MALE),
        )
        sara = Student.objects.get(admission_number="S-2")
        self.assertEqual((sara.first_name, sara.last_name), ("Sara", "Ahmed"))
        self.assertEqual(Enrollment.objects.filter(academic_year=self.year, classroom=self.grade6).count(), 2)

    def test_any_error_imports_nothing_and_lists_rows(self):
        csv_text = (
            "admission_number,first_name,last_name,class,section,date_of_birth\n"
            "S-1,Ali,Khan,Grade 6,A,\n"
            "S-3,Bad,Date,Grade 6,A,31/31/2014\n"
            "S-4,No,Class,Grade 9,A,\n"
            "S-1,Dup,Row,Grade 6,A,\n"
        )
        response = self.client.post(reverse("academics:student_import"), {"file": _upload("s.csv", csv_text)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was imported")
        self.assertContains(response, "Row 3:")
        self.assertContains(response, "Class Grade 9 A does not exist")
        self.assertContains(response, "appears twice")
        self.assertFalse(Student.objects.exists())

    def test_xlsx_import_can_create_missing_classes(self):
        from openpyxl import Workbook

        book = Workbook()
        book.active.append(["admission_number", "first_name", "last_name", "class", "section"])
        book.active.append([1001, "Zara", "Ali", "Grade 7", "B"])
        buffer = io.BytesIO()
        book.save(buffer)
        response = self.client.post(
            reverse("academics:student_import"),
            {"file": _upload("students.xlsx", buffer.getvalue()), "create_classes": "1"},
        )
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(admission_number="1001")
        self.assertEqual(student.enrollments.get().classroom.name, "Grade 7")

    def test_template_download_and_teacher_is_blocked(self):
        template = self.client.get(reverse("academics:student_import_template"))
        self.assertTrue(template.content.decode().startswith("admission_number,first_name"))
        self.client.force_login(User.objects.create_user(username="t-import", role="teacher"))
        self.assertEqual(self.client.get(reverse("academics:student_import")).status_code, 403)


class PromotionTests(TestCase):
    def setUp(self):
        self.old = AcademicYear.objects.create(
            name="2026-2027", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30), is_active=True
        )
        self.new = AcademicYear.objects.create(
            name="2027-2028", start_date=date(2027, 8, 1), end_date=date(2028, 6, 30)
        )
        self.g6 = Classroom.objects.create(name="Grade 6", section="A", academic_year=self.old)
        self.g7 = Classroom.objects.create(name="Grade 7", section="A", academic_year=self.old)
        self.passer = self._student("P-1", self.g6)
        self.repeater = self._student("P-2", self.g6)
        self.senior = self._student("P-3", self.g7)
        self.client.force_login(User.objects.create_user(username="boss-promote", role="principal"))

    def _student(self, number, classroom):
        student = Student.objects.create(admission_number=number, first_name="S", last_name=number)
        Enrollment.objects.create(student=student, classroom=classroom, academic_year=self.old)
        return student

    def test_copy_then_promote_with_repeaters_and_leavers(self):
        self.client.post(reverse("academics:promote"), {"target": self.new.pk, "action": "copy_classes"})
        new_g6 = Classroom.objects.get(academic_year=self.new, name="Grade 6")
        new_g7 = Classroom.objects.get(academic_year=self.new, name="Grade 7")

        page = self.client.get(reverse("academics:promote"), {"to": self.new.pk})
        suggested = {c.pk: c.suggested for c in page.context["source_classes"]}
        self.assertEqual(suggested, {self.g6.pk: str(new_g7.pk), self.g7.pk: "leave"})

        response = self.client.post(
            reverse("academics:promote"),
            {
                "target": self.new.pk,
                f"class_{self.g6.pk}": str(new_g7.pk),
                f"class_{self.g7.pk}": "leave",
                "repeat": [str(self.repeater.pk)],
                "make_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.passer.enrollments.get(academic_year=self.new).classroom, new_g7)
        self.assertEqual(self.repeater.enrollments.get(academic_year=self.new).classroom, new_g6)
        self.senior.refresh_from_db()
        self.assertFalse(self.senior.is_active)
        self.new.refresh_from_db()
        self.old.refresh_from_db()
        self.assertTrue(self.new.is_active)
        self.assertFalse(self.old.is_active)

    def test_promoting_twice_does_not_duplicate(self):
        target = Classroom.objects.create(name="Grade 7", section="A", academic_year=self.new)
        plan = {self.g6.pk: str(target.pk), self.g7.pk: "skip"}
        promote(self.old, self.new, plan, set(), make_active=False)
        result = promote(self.old, self.new, plan, set(), make_active=False)
        self.assertEqual((result.promoted, result.already_enrolled), (0, 2))
        self.assertEqual(Enrollment.objects.filter(academic_year=self.new).count(), 2)

    def test_only_principal_can_promote(self):
        self.client.force_login(User.objects.create_user(username="office-promote", role="office"))
        self.assertEqual(self.client.get(reverse("academics:promote")).status_code, 403)


class ParentLoginTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="Parent year", start_date=date(2026, 8, 1), end_date=date(2027, 6, 30), is_active=True
        )
        classroom = Classroom.objects.create(name="Grade 3", section="A", academic_year=self.year)
        self.first = Student.objects.create(
            admission_number="F-1", first_name="Amna", last_name="Raza",
            guardian_name="Bilal Raza", guardian_phone="+92 300 7654321",
        )
        self.sibling = Student.objects.create(
            admission_number="F-2", first_name="Hadi", last_name="Raza", guardian_phone="0300-7654321"
        )
        for student in (self.first, self.sibling):
            Enrollment.objects.create(student=student, classroom=classroom, academic_year=self.year)
        self.client.force_login(User.objects.create_user(username="office-parents", role="office"))

    def test_create_login_links_siblings_and_shows_password_once(self):
        self.client.post(reverse("academics:parent_logins"), {"student": self.first.pk, "action": "create"})
        credentials = self.client.get(reverse("academics:parent_logins")).context["credentials"]
        self.assertEqual(credentials["username"], "03007654321")
        self.assertIn("wa.me/923007654321", credentials["whatsapp"])
        parent = User.objects.get(username="03007654321")
        self.assertEqual((parent.role, parent.first_name), ("parent", "Bilal"))
        self.assertTrue(parent.check_password(credentials["password"]))
        self.assertIsNone(self.client.get(reverse("academics:parent_logins")).context["credentials"])

        self.client.post(reverse("academics:parent_logins"), {"student": self.sibling.pk, "action": "create"})
        self.sibling.refresh_from_db()
        self.assertEqual(self.sibling.guardian_user, parent)
        parent.refresh_from_db()
        self.assertTrue(parent.check_password(credentials["password"]))

    def test_new_password_replaces_the_old_one(self):
        self.client.post(reverse("academics:parent_logins"), {"student": self.first.pk, "action": "create"})
        old = self.client.get(reverse("academics:parent_logins")).context["credentials"]["password"]
        self.client.post(reverse("academics:parent_logins"), {"student": self.first.pk, "action": "reset"})
        new = self.client.get(reverse("academics:parent_logins")).context["credentials"]["password"]
        parent = User.objects.get(username="03007654321")
        self.assertNotEqual(old, new)
        self.assertTrue(parent.check_password(new))
        self.assertFalse(parent.check_password(old))

    def test_username_belonging_to_staff_is_not_reused(self):
        User.objects.create_user(username="03007654321", role="teacher")
        self.client.post(reverse("academics:parent_logins"), {"student": self.first.pk, "action": "create"})
        self.first.refresh_from_db()
        self.assertIsNone(self.first.guardian_user)

    def test_teacher_cannot_manage_parent_logins(self):
        self.client.force_login(User.objects.create_user(username="t-parents", role="teacher"))
        self.assertEqual(self.client.get(reverse("academics:parent_logins")).status_code, 403)
