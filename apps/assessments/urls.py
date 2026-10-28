from django.urls import path

from apps.assessments import exam_views, views

app_name = "assessments"

urlpatterns = [
    path("", views.index, name="index"),
    path("exams/new/", exam_views.exam_create, name="exam-create"),
    path("exams/<int:exam_id>/date-sheet/", exam_views.date_sheet, name="date-sheet"),
    path("exams/<int:exam_id>/marks/<int:subject_id>/", exam_views.class_marks, name="class-marks"),
    path("exams/<int:exam_id>/result-cards/", exam_views.result_cards, name="result-cards"),
    path("marks/entry/", views.enter_marks, name="mark-entry"),
    path("review/", views.review, name="review"),
    path("results/<int:exam_id>/", views.result_sheet, name="result-sheet"),
]
