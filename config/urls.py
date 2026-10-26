from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="dashboard:index", permanent=False)),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("academics/", include("apps.academics.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("assessments/", include("apps.assessments.urls")),
    path("homework/", include("apps.homework.urls")),
    path("fees/", include("apps.fees.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("portal/", include("apps.student_portal.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
