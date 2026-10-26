from django.urls import path

from . import views

app_name = "student_portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("classroom/", views.classroom, name="classroom"),
    path("study-guides/", views.study_guides, name="study_guides"),
    path("balance/", views.balance, name="balance"),
    path("id-card/", views.id_card, name="id_card"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("notifications/", views.notifications, name="notifications"),
]
