from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView
from django.views.static import serve


@login_required
def protected_media(request, path):
    """Student photos and study files are private: only signed-in users may open them."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)


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
    path(f"{settings.MEDIA_URL.strip('/')}/<path:path>", protected_media, name="media"),
]
