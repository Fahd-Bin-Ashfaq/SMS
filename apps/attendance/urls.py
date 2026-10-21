from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.entry, name="entry"),
    path("monthly/", views.monthly_summary, name="monthly-summary"),
]
