from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .permissions import can_access_assignment, role_required

User = get_user_model()


class AccountLoginTests(TestCase):
    def setUp(self):
        self.password = "Valid-School-Password-2026!"
        self.user = User.objects.create_user(
            username="teacher1",
            email="teacher@example.com",
            password=self.password,
        )

    def test_staff_login_page_uses_csrf_form_and_password_reset_link(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, reverse("password_reset"))
        self.assertContains(response, "auth-card")
        self.assertContains(response, "Welcome back")

    def test_staff_can_log_in(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.password, "next": "/"},
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_invalid_login_shows_error(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "incorrect"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign-in failed")


class RolePermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_role_required_denies_authenticated_wrong_role(self):
        @role_required(User.Role.PRINCIPAL)
        def principal_view(request):
            from django.http import HttpResponse

            return HttpResponse("allowed")

        request = self.factory.get("/restricted/")
        request.user = User(username="teacher", role=User.Role.TEACHER)

        response = principal_view(request)

        self.assertEqual(response.status_code, 403)

    def test_role_required_redirects_anonymous_users_to_login(self):
        @role_required(User.Role.PRINCIPAL)
        def principal_view(request):
            from django.http import HttpResponse

            return HttpResponse("allowed")

        request = self.factory.get("/restricted/")
        request.user = AnonymousUser()

        response = principal_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_teacher_can_access_only_their_own_assignment(self):
        user = User(pk=10, role=User.Role.TEACHER)

        class Assignment:
            teacher = type("TeacherRef", (), {"user_id": 10})()

        self.assertTrue(can_access_assignment(user, Assignment()))
        Assignment.teacher = type("TeacherRef", (), {"user_id": 11})()
        self.assertFalse(can_access_assignment(user, Assignment()))

    def test_new_accounts_default_to_non_principal_role(self):
        self.assertEqual(User().role, User.Role.TEACHER)
