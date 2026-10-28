from django.urls import path

from . import staff_views, views

app_name = "student_portal"

urlpatterns = [
    path("", views.home, name="home"),
    path("switch-child/", views.switch_child, name="switch_child"),
    path("classroom/", views.classroom, name="classroom"),
    path("homework/", views.homework, name="homework"),
    path("homework/<int:pk>/", views.homework_detail, name="homework_detail"),
    path("exams/", views.exams, name="exams"),
    path("exams/<int:exam_id>/result/", views.result_card, name="result_card"),
    path("study-guides/", views.study_guides, name="study_guides"),
    path("balance/", views.balance, name="balance"),
    path("id-card/", views.id_card, name="id_card"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("notifications/", views.notifications, name="notifications"),
    path("notices/manage/", staff_views.notices, name="notices"),
    path("notices/<int:pk>/delete/", staff_views.notice_delete, name="notice_delete"),
]
