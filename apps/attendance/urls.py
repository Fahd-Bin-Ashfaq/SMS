from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.entry, name="entry"),
    path("monthly/", views.monthly_summary, name="monthly-summary"),
    path("alerts/", views.absence_alerts, name="absence-alerts"),
    path("alerts/<int:record_id>/send/", views.send_absence_alert, name="send-absence-alert"),
]
