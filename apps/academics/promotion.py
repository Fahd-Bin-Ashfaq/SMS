"""Move students from one academic year into the next."""

import re
from dataclasses import dataclass

from django.db import transaction

from .models import AcademicYear, Classroom, Enrollment

LEAVE = "leave"
SKIP = "skip"


@dataclass
class PromotionResult:
    promoted: int = 0
    repeated: int = 0
    left: int = 0
    already_enrolled: int = 0


def _next_grade_name(name):
    match = re.search(r"\d+", name)
    if not match:
        return None
    return f"{name[:match.start()]}{int(match.group()) + 1}{name[match.end():]}"


def suggest_plan(source_classes, target_classes):
    """Guess where each class goes: Grade 6 A -> Grade 7 A; the top grade leaves."""
    by_name = {(c.name.lower(), c.section.lower()): c for c in target_classes}
    grades = [int(m.group()) for c in source_classes if (m := re.search(r"\d+", c.name))]
    top_grade = max(grades) if grades else None
    plan = {}
    for classroom in source_classes:
        next_name = _next_grade_name(classroom.name)
        target = by_name.get((next_name.lower(), classroom.section.lower())) if next_name else None
        if target is not None:
            plan[classroom.pk] = str(target.pk)
        else:
            match = re.search(r"\d+", classroom.name)
            plan[classroom.pk] = LEAVE if match and int(match.group()) == top_grade else SKIP
    return plan


def copy_classes(source_year, target_year):
    """Create the same classes (name, section, class teacher) in the target year."""
    created = 0
    for classroom in Classroom.objects.filter(academic_year=source_year):
        _, was_created = Classroom.objects.get_or_create(
            name=classroom.name,
            section=classroom.section,
            academic_year=target_year,
            defaults={"class_teacher": classroom.class_teacher},
        )
        created += was_created
    return created


def promote(source_year, target_year, plan, repeaters, make_active):
    """Enroll students of ``source_year`` into ``target_year`` according to ``plan``.

    ``plan`` maps a source class pk to a target class pk, LEAVE or SKIP.
    ``repeaters`` are student pks who stay in the same grade (same class name and
    section in the new year). Students already enrolled in the target year are
    left alone, so running it again does not duplicate anything.
    """
    result = PromotionResult()
    targets = {c.pk: c for c in Classroom.objects.filter(academic_year=target_year)}
    same_class = {(c.name.lower(), c.section.lower()): c for c in targets.values()}
    enrolled = set(
        Enrollment.objects.filter(academic_year=target_year).values_list("student_id", flat=True)
    )
    with transaction.atomic():
        for enrollment in Enrollment.objects.filter(
            academic_year=source_year,
            status=Enrollment.Status.ACTIVE,
            student__is_active=True,
        ).select_related("student", "classroom"):
            choice = plan.get(enrollment.classroom_id, SKIP)
            student = enrollment.student
            if student.pk in enrolled:
                result.already_enrolled += 1
                continue
            if student.pk in repeaters:
                key = (enrollment.classroom.name.lower(), enrollment.classroom.section.lower())
                target = same_class.get(key)
                if target is None:
                    target = Classroom.objects.create(
                        name=enrollment.classroom.name,
                        section=enrollment.classroom.section,
                        academic_year=target_year,
                        class_teacher=enrollment.classroom.class_teacher,
                    )
                    same_class[key] = target
                Enrollment.objects.create(student=student, classroom=target, academic_year=target_year)
                result.repeated += 1
            elif choice == LEAVE:
                student.is_active = False
                student.save(update_fields=["is_active"])
                result.left += 1
            elif choice != SKIP and int(choice) in targets:
                Enrollment.objects.create(
                    student=student, classroom=targets[int(choice)], academic_year=target_year
                )
                result.promoted += 1
        if make_active:
            AcademicYear.objects.filter(is_active=True).update(is_active=False)
            AcademicYear.objects.filter(pk=target_year.pk).update(is_active=True)
    return result
