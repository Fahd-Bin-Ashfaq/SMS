from django.urls import path

from .views import (
    StaffLoginView,
    StaffLogoutView,
    StaffPasswordResetCompleteView,
    StaffPasswordResetConfirmView,
    StaffPasswordResetDoneView,
    StaffPasswordResetView,
)


urlpatterns = [
    path("login/", StaffLoginView.as_view(), name="login"),
    path("logout/", StaffLogoutView.as_view(), name="logout"),
    path("password-reset/", StaffPasswordResetView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        StaffPasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        StaffPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        StaffPasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
]
