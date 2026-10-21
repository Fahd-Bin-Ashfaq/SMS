from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden


def has_role(user, *roles):
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and user.role in roles
    )


def role_required(*roles):
    """Require an authenticated account with one of the specified staff roles."""
    if not roles:
        raise ValueError("role_required requires at least one role")

    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_role(user, *roles):
                return HttpResponseForbidden("You do not have permission to access this page.")
            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def can_access_assignment(user, assignment):
    """Principals can access all assignments; teachers can access only their own."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or has_role(user, "principal"):
        return True
    if not has_role(user, "teacher"):
        return False
    teacher = getattr(assignment, "teacher", None)
    return teacher is not None and getattr(teacher, "user_id", None) == user.pk
