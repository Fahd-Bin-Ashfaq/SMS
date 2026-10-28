from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student

User = get_user_model()


class ParentPortalTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        year = AcademicYear.objects.create(
            name="Family year", start_date=today - timedelta(days=60), end_date=today + timedelta(days=200), is_active=True
        )
        classroom = Classroom.objects.create(name="Grade 2", section="A", academic_year=year)
        self.parent = User.objects.create_user(username="03001112222", role="parent")
        self.elder = Student.objects.create(admission_number="C-1", first_name="Elder", last_name="Child", guardian_user=self.parent)
        self.younger = Student.objects.create(admission_number="C-2", first_name="Younger", last_name="Child", guardian_user=self.parent)
        self.stranger = Student.objects.create(admission_number="C-3", first_name="Stranger", last_name="Kid")
        for student in (self.elder, self.younger, self.stranger):
            Enrollment.objects.create(student=student, classroom=classroom, academic_year=year)

    def test_parent_is_sent_to_the_portal_and_sees_their_first_child(self):
        self.client.force_login(self.parent)
        self.assertRedirects(self.client.get("/dashboard/"), "/portal/", fetch_redirect_response=False)
        response = self.client.get("/portal/")
        self.assertEqual(response.context["student"], self.elder)
        self.assertEqual(list(response.context["children"]), [self.elder, self.younger])
        self.assertContains(response, "Viewing Elder")

    def test_parent_can_switch_only_to_their_own_children(self):
        self.client.force_login(self.parent)
        self.client.post("/portal/switch-child/", {"student": self.younger.pk})
        self.assertEqual(self.client.get("/portal/profile/").context["student"], self.younger)
        self.client.post("/portal/switch-child/", {"student": self.stranger.pk})
        self.assertEqual(self.client.get("/portal/profile/").context["student"], self.younger)

    def test_parent_without_children_sees_not_linked_page(self):
        lonely = User.objects.create_user(username="03009998888", role="parent")
        self.client.force_login(lonely)
        self.assertEqual(self.client.get("/portal/").status_code, 403)

    def test_parent_cannot_open_staff_pages(self):
        self.client.force_login(self.parent)
        for url in ("/fees/", "/fees/overview/", "/attendance/", "/homework/", "/academics/students/"):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (302, 403))
