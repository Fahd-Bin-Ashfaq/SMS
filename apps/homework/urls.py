from django.urls import path

from apps.homework import views

app_name = "homework"

urlpatterns = [
    path("", views.index, name="index"),
    path("assign/", views.create, name="create"),
    path("<int:homework_id>/edit/", views.edit, name="edit"),
    path("review/", views.review, name="review"),
]
