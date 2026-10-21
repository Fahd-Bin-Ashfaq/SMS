from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("academics/", include("apps.academics.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("assessments/", include("apps.assessments.urls")),
    path("homework/", include("apps.homework.urls")),
    path("fees/", include("apps.fees.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
]
