"""Turn marks into result cards: totals, percentage, grade and class position."""

from decimal import Decimal

from .models import ResultRemark, StudentMark, active_enrollments

PASS_PERCENT = Decimal("33")
# (lowest percentage, grade), highest first.
GRADES = (
    (Decimal("90"), "A+"),
    (Decimal("80"), "A"),
    (Decimal("70"), "B"),
    (Decimal("60"), "C"),
    (Decimal("50"), "D"),
    (PASS_PERCENT, "E"),
    (Decimal("0"), "F"),
)


def grade_for(percent):
    if percent is None:
        return ""
    return next(grade for lowest, grade in GRADES if percent >= lowest)


def _percent(obtained, maximum):
    if not maximum:
        return None
    return (obtained * 100 / maximum).quantize(Decimal("0.1"))


def class_results(exam):
    """Result rows for every active student in the exam's class, best first.

    Each row has the student, one cell per exam subject, the total, percentage,
    grade, pass/fail and position. Students tied on total share a position.
    """
    exam_subjects = list(exam.subjects.select_related("subject").order_by("subject__name"))
    maximum_total = sum((es.maximum_marks for es in exam_subjects), Decimal("0"))
    students = [
        enrollment.student
        for enrollment in active_enrollments()
        .filter(classroom=exam.classroom, academic_year=exam.academic_year)
        .select_related("student")
        .order_by("student__first_name", "student__last_name")
    ]
    marks = {
        (mark.student_id, mark.subject_id): mark.marks_awarded
        for mark in StudentMark.objects.filter(exam=exam)
    }
    remarks = dict(ResultRemark.objects.filter(exam=exam).values_list("student_id", "remarks"))

    rows = []
    for student in students:
        cells = []
        obtained = Decimal("0")
        entered = 0
        failed_subject = False
        for exam_subject in exam_subjects:
            value = marks.get((student.pk, exam_subject.subject_id))
            percent = _percent(value, exam_subject.maximum_marks) if value is not None else None
            if value is not None:
                obtained += value
                entered += 1
                failed_subject = failed_subject or percent < PASS_PERCENT
            cells.append({"exam_subject": exam_subject, "marks": value, "grade": grade_for(percent)})
        percent = _percent(obtained, maximum_total) if entered else None
        complete = entered == len(exam_subjects) and entered > 0
        rows.append(
            {
                "student": student,
                "cells": cells,
                "obtained": obtained if entered else None,
                "percent": percent,
                "grade": grade_for(percent),
                "complete": complete,
                "passed": complete and not failed_subject and percent >= PASS_PERCENT,
                "remarks": remarks.get(student.pk, ""),
                "position": None,
            }
        )

    ranked = sorted((row for row in rows if row["obtained"] is not None), key=lambda row: row["obtained"], reverse=True)
    for index, row in enumerate(ranked):
        if index and row["obtained"] == ranked[index - 1]["obtained"]:
            row["position"] = ranked[index - 1]["position"]
        else:
            row["position"] = index + 1
    rows.sort(key=lambda row: (row["position"] is None, row["position"] or 0, row["student"].first_name))
    return {"exam_subjects": exam_subjects, "maximum_total": maximum_total, "rows": rows, "class_size": len(rows)}
