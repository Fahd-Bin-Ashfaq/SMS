from django.urls import path

from . import views

app_name = "fees"

urlpatterns = [
    path("", views.dues, name="dues"),
    path("overview/", views.overview, name="overview"),
    path("charges/new/", views.charge_create, name="charge-create"),
    path("charges/monthly/", views.generate_fees, name="generate"),
    path("payments/new/", views.payment_create, name="payment-create"),
    path("students/<int:student_id>/", views.student_account, name="student-account"),
    path("students/<int:student_id>/remind/", views.remind, name="remind"),
    path("receipts/<int:payment_id>/", views.receipt, name="receipt"),
    path("staff/", views.staff_list, name="staff"),
    path("staff/new/", views.staff_form, name="staff-create"),
    path("staff/<int:staff_id>/edit/", views.staff_form, name="staff-edit"),
    path("staff/<int:staff_id>/pay/", views.staff_pay, name="staff-pay"),
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/new/", views.expense_create, name="expense-create"),
]
