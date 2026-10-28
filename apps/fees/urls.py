from django.urls import path

from . import views

app_name = "fees"

urlpatterns = [
    path("", views.dues, name="dues"),
    path("overview/", views.overview, name="overview"),
    path("charges/new/", views.charge_create, name="charge-create"),
    path("charges/monthly/", views.generate_fees, name="generate"),
    path("charges/bulk/", views.bulk_charges, name="bulk-charge"),
    path("charges/late-fees/", views.late_fees, name="late-fees"),
    path("daily-report/", views.daily_report, name="daily-report"),
    path("students/<int:student_id>/concession/", views.concession, name="concession"),
    path("payments/new/", views.payment_create, name="payment-create"),
    path("students/<int:student_id>/", views.student_account, name="student-account"),
    path("students/<int:student_id>/remind/", views.remind, name="remind"),
    path("receipts/<int:payment_id>/", views.receipt, name="receipt"),
    path("staff/", views.staff_list, name="staff"),
    path("staff/new/", views.staff_form, name="staff-create"),
    path("staff/<int:staff_id>/edit/", views.staff_form, name="staff-edit"),
    path("staff/<int:staff_id>/pay/", views.staff_pay, name="staff-pay"),
    path("staff/<int:staff_id>/login/", views.staff_login, name="staff-login"),
    path("staff/<int:staff_id>/advance/", views.staff_advance, name="staff-advance"),
    path("staff/attendance/", views.staff_attendance, name="staff-attendance"),
    path("salary-slips/<int:expense_id>/", views.salary_slip, name="salary-slip"),
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/new/", views.expense_create, name="expense-create"),
]
