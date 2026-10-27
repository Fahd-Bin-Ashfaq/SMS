from django.conf import settings
from django.templatetags.static import static

LOGO_NAMES = ("logo.png", "logo.jpg", "logo.jpeg", "logo.svg", "logo.webp")


def _logo_url():
    folder = settings.BASE_DIR / "static" / "school"
    for name in LOGO_NAMES:
        if (folder / name).is_file():
            return static(f"school/{name}")
    return ""


def school(request):
    """School name, campus, contact and logo for every template."""
    return {
        "school_name": settings.SCHOOL_NAME,
        "school_campus": settings.SCHOOL_CAMPUS,
        "school_contact": settings.SCHOOL_CONTACT,
        "school_logo_url": _logo_url(),
    }
