from apps.academics.models import TeacherAssignment


def user_role(user):
    return getattr(user, "role", "")


def is_reviewer(user):
    return user_role(user) in {"principal", "office"}


def can_access_exam(user, exam):
    if is_reviewer(user):
        return True
    if user_role(user) != "teacher":
        return False
    return TeacherAssignment.objects.filter(
        teacher__user=user, classroom=exam.classroom
    ).exists()
