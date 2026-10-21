from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    Classroom,
    Enrollment,
    Student,
    Subject,
    Teacher,
    TeacherAssignment,
)
from apps.assessments.models import Exam, ExamSubject, StudentMark
from apps.attendance.models import AttendanceRecord
from apps.homework.models import Homework


DEMO_PASSWORD = "Demo123!"

STUDENT_NAMES = (
    ("Ayaan", "Khan"),
    ("Areeba", "Ahmed"),
    ("Hamza", "Malik"),
    ("Zoya", "Sheikh"),
    ("Rayyan", "Ali"),
    ("Hania", "Hussain"),
    ("Ibrahim", "Qureshi"),
    ("Mishal", "Raza"),
    ("Saad", "Iqbal"),
    ("Noor", "Farooq"),
)

TEACHER_NAMES = (
    ("demo.teacher1", "Amina", "Khan"),
    ("demo.teacher2", "Usman", "Ahmed"),
    ("demo.teacher3", "Sara", "Malik"),
)

SUBJECT_DATA = (
    ("Mathematics", "DEMO-MATH"),
    ("English", "DEMO-ENG"),
    ("Science", "DEMO-SCI"),
)


class Command(BaseCommand):
    help = "Create or refresh fictional school records and demo-only login accounts."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo data can only be seeded when DEBUG=true.")

        with transaction.atomic():
            self.seed()
        self.stdout.write(self.style.SUCCESS("Demo school data is ready."))
        self.stdout.write(f"Demo password for all demo accounts: {DEMO_PASSWORD}")

    def seed(self):
        User = get_user_model()
        today = timezone.localdate()
        year_start = today.year if today.month >= 8 else today.year - 1
        year_end = year_start + 1
        year = AcademicYear.objects.filter(is_active=True).first()
        if year is None:
            year, _ = AcademicYear.objects.get_or_create(
                name=f"{year_start}-{year_end}",
                defaults={
                    "start_date": date(year_start, 8, 1),
                    "end_date": date(year_end, 6, 30),
                    "is_active": True,
                },
            )
            if not year.is_active:
                year.is_active = True
                year.save(update_fields=["is_active"])

        classroom, _ = Classroom.objects.get_or_create(
            name="Grade 6",
            section="A",
            academic_year=year,
        )
        principal = self.demo_user(
            User,
            username="demo.principal",
            first_name="Alex",
            last_name="Principal",
            role="principal",
        )

        teachers = []
        for username, first_name, last_name in TEACHER_NAMES:
            user = self.demo_user(
                User,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role="teacher",
            )
            teacher, _ = Teacher.objects.get_or_create(user=user)
            teachers.append((user, teacher))

        subjects = [
            Subject.objects.get_or_create(code=code, defaults={"name": name})[0]
            for name, code in SUBJECT_DATA
        ]
        for (user, teacher), subject in zip(teachers, subjects):
            TeacherAssignment.objects.get_or_create(
                teacher=teacher,
                classroom=classroom,
                subject=subject,
            )

        students = []
        for index, (first_name, last_name) in enumerate(STUDENT_NAMES, start=1):
            student, _ = Student.objects.update_or_create(
                admission_number=f"DEMO-{index:03}",
                defaults={
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_active": True,
                },
            )
            enrollment, created = Enrollment.objects.get_or_create(
                student=student,
                academic_year=year,
                defaults={"classroom": classroom, "status": Enrollment.Status.ACTIVE},
            )
            if not created and (
                enrollment.classroom_id != classroom.pk
                or enrollment.status != Enrollment.Status.ACTIVE
            ):
                enrollment.classroom = classroom
                enrollment.status = Enrollment.Status.ACTIVE
                enrollment.save(update_fields=["classroom", "status"])
            students.append((student, enrollment))

        student_user = self.demo_user(
            User,
            username="demo.student",
            first_name=students[0][0].first_name,
            last_name=students[0][0].last_name,
            role="student",
        )
        students[0][0].user = student_user
        students[0][0].save(update_fields=["user"])

        if year.start_date <= today <= year.end_date:
            statuses = (
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.PRESENT,
                AttendanceRecord.Status.LATE,
                AttendanceRecord.Status.LATE,
                AttendanceRecord.Status.ABSENT,
            )
            for (student, enrollment), status in zip(students, statuses):
                AttendanceRecord.objects.update_or_create(
                    enrollment=enrollment,
                    date=today,
                    defaults={"status": status, "recorded_by": principal},
                )

            for index, ((user, _teacher), subject) in enumerate(
                zip(teachers, subjects), start=1
            ):
                assigned_date = today
                Homework.objects.update_or_create(
                    classroom=classroom,
                    subject=subject,
                    assigned_by=user,
                    title=f"Demo {subject.name} practice",
                    defaults={
                        "description": f"Sample {subject.name.lower()} homework for the demo class.",
                        "assigned_date": assigned_date,
                        "due_date": assigned_date + timedelta(days=index + 2),
                    },
                )

            exam, _ = Exam.objects.get_or_create(
                academic_year=year,
                classroom=classroom,
                name="Demo Midterm",
                defaults={"date": today - timedelta(days=5)},
            )
            for subject_index, subject in enumerate(subjects):
                exam_subject, _ = ExamSubject.objects.get_or_create(
                    exam=exam,
                    subject=subject,
                    defaults={"maximum_marks": 100},
                )
                for student_index, (student, _enrollment) in enumerate(students):
                    StudentMark.objects.update_or_create(
                        exam=exam,
                        student=student,
                        subject=subject,
                        defaults={
                            "marks_awarded": 68 + ((student_index * 3 + subject_index * 5) % 31),
                            "updated_by": teachers[subject_index][0],
                        },
                    )

        self.stdout.write(f"  Students: {len(students)} fictional records")
        self.stdout.write(f"  Teachers: {len(teachers)} demo accounts")
        self.stdout.write("  Principal: demo.principal")
        self.stdout.write("  Student login: demo.student (linked to DEMO-001)")

    @staticmethod
    def demo_user(User, *, username, first_name, last_name, role):
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.is_active = True
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user
