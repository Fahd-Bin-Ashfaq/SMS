from django.urls import path

from . import views

app_name = "fees"

urlpatterns = [
    path("", views.dues, name="dues"),
    path("charges/new/", views.charge_create, name="charge-create"),
    path("payments/new/", views.payment_create, name="payment-create"),
    path("students/<int:student_id>/", views.student_account, name="student-account"),
    path("receipts/<int:payment_id>/", views.receipt, name="receipt"),
]
