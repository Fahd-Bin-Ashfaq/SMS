from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from .forms import StaffAuthenticationForm


class StaffLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = StaffAuthenticationForm
    redirect_authenticated_user = True

    def form_invalid(self, form):
        messages.error(self.request, "Sign-in failed. Check your username and password.")
        return super().form_invalid(form)


class StaffLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("login")

    def post(self, request, *args, **kwargs):
        messages.success(request, "You have been signed out.")
        return super().post(request, *args, **kwargs)


class StaffPasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset_form.html"
    email_template_name = "accounts/password_reset_email.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")


class StaffPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class StaffPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")


class StaffPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
