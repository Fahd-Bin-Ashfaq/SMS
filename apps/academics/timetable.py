from datetime import timedelta

from apps.accounts.permissions import has_role

from .models import TimetableEntry


WEEKDAYS = tuple(TimetableEntry.Day)


def can_edit_timetable(user, classroom):
    """Principals edit every timetable; a teacher edits only their own homeroom's."""
    if has_role(user, "principal"):
        return True
    if not has_role(user, "teacher") or classroom.class_teacher_id is None:
        return False
    return classroom.class_teacher.user_id == user.pk


def build_grid(entries):
    """Arrange entries into weekday columns and time-slot rows."""
    entries = list(entries)
    days = [day for day in WEEKDAYS if day < TimetableEntry.Day.SATURDAY]
    if any(entry.day == TimetableEntry.Day.SATURDAY for entry in entries):
        days.append(TimetableEntry.Day.SATURDAY)
    slots = sorted({(entry.start_time, entry.end_time) for entry in entries})
    by_slot = {(entry.day, entry.start_time, entry.end_time): entry for entry in entries}
    rows = [
        {
            "start": start,
            "end": end,
            "cells": [by_slot.get((day, start, end)) for day in days],
        }
        for start, end in slots
    ]
    return {"days": [(day.value, day.label) for day in days], "rows": rows}


def day_periods(classroom, day):
    return list(
        classroom.timetable_entries.filter(day=day).select_related("subject", "teacher__user")
    )


def next_period(classroom, now):
    """Return (entry, date) for the next subject period starting after ``now``."""
    entries = list(
        classroom.timetable_entries.filter(subject__isnull=False)
        .select_related("subject", "teacher__user")
        .order_by("day", "start_time")
    )
    if not entries:
        return None, None
    for offset in range(8):
        date = now.date() + timedelta(days=offset)
        for entry in entries:
            if entry.day != date.weekday():
                continue
            if offset == 0 and entry.end_time <= now.time():
                continue
            return entry, date
    return None, None


def is_in_progress(entry, date, now):
    if entry is None or date != now.date():
        return False
    return entry.start_time <= now.time() < entry.end_time


def school_hours(classroom):
    """Summarise the timetable as days and opening hours for display."""
    entries = list(classroom.timetable_entries.all())
    if not entries:
        return None
    days = sorted({entry.day for entry in entries})
    labels = dict(TimetableEntry.Day.choices)
    if days == list(range(days[0], days[-1] + 1)) and len(days) > 1:
        day_text = f"{labels[days[0]][:3]}–{labels[days[-1]][:3]}"
    else:
        day_text = ", ".join(labels[day][:3] for day in days)
    return {
        "days": day_text,
        "start": min(entry.start_time for entry in entries),
        "end": max(entry.end_time for entry in entries),
    }
