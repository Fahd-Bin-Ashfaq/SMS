from django.urls import path

from apps.assessments import views

app_name = "assessments"

urlpatterns = [
    path("", views.index, name="index"),
    path("marks/entry/", views.enter_marks, name="mark-entry"),
    path("review/", views.review, name="review"),
    path("results/<int:exam_id>/", views.result_sheet, name="result-sheet"),
]
