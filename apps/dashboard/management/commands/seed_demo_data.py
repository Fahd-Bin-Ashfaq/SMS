import random
from datetime import date, time, timedelta
from decimal import Decimal

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
    TimetableEntry,
)
from apps.assessments.models import Exam, ExamSubject, StudentMark
from apps.attendance.models import AttendanceRecord
from apps.fees.models import Expense, FeeCharge, FeePayment, StaffMember
from apps.homework.models import Homework
from apps.student_portal.models import Notification, StudyGuide


DEMO_PASSWORD = "1234"
STUDENTS_PER_CLASS = 10
ATTENDANCE_DAYS = 10
MONTHLY_FEE = Decimal("3000.00")
# Support staff without a login: name, designation, monthly salary.
SUPPORT_STAFF = (
    ("Bashir Ahmed", "Security guard", Decimal("28000.00")),
    ("Nasreen Bibi", "Cleaner", Decimal("25000.00")),
    ("Kashif Ali", "Peon", Decimal("25000.00")),
)
MONTHLY_EXPENSES = (
    (Expense.Category.UTILITIES, "Electricity bill", Decimal("18500.00"), 12),
    (Expense.Category.UTILITIES, "Gas & water bill", Decimal("4200.00"), 14),
    (Expense.Category.UTILITIES, "Internet", Decimal("3000.00"), 5),
    (Expense.Category.SUPPLIES, "Stationery and chalk", Decimal("6200.00"), 3),
)

CLASSROOMS = (
    ("Grade 6", "A"),
    ("Grade 6", "B"),
    ("Grade 7", "A"),
    ("Grade 7", "B"),
    ("Grade 8", "A"),
)

FIRST_NAMES = (
    "Ayaan", "Areeba", "Hamza", "Zoya", "Rayyan", "Hania", "Ibrahim", "Mishal",
    "Saad", "Noor", "Ali", "Fatima", "Bilal", "Ayesha", "Umar", "Maryam",
    "Hassan", "Zainab", "Daniyal", "Iqra", "Talha", "Mahnoor", "Arham", "Eman",
    "Fahad",
)

LAST_NAMES = (
    "Khan", "Ahmed", "Malik", "Sheikh", "Ali", "Hussain", "Qureshi", "Raza",
    "Iqbal", "Farooq", "Butt", "Chaudhry", "Siddiqui", "Mirza", "Javed",
)

# (username, first name, last name, subject name, subject code)
TEACHERS = (
    ("teacher1", "Amina", "Khan", "Mathematics", "DEMO-MATH"),
    ("teacher2", "Usman", "Ahmed", "English", "DEMO-ENG"),
    ("teacher3", "Sara", "Malik", "Science", "DEMO-SCI"),
    ("teacher4", "Bilal", "Hussain", "Urdu", "DEMO-URDU"),
    ("teacher5", "Hina", "Qureshi", "Islamiat", "DEMO-ISL"),
    ("teacher6", "Kamran", "Siddiqui", "Computer", "DEMO-COMP"),
)

FEMALE_NAMES = {
    "Areeba", "Zoya", "Hania", "Mishal", "Noor", "Fatima", "Ayesha", "Maryam",
    "Zainab", "Iqra", "Mahnoor", "Eman",
}

AREAS = (
    "Gulshan-e-Iqbal", "North Nazimabad", "Gulistan-e-Jauhar", "PECHS",
    "Clifton", "Malir", "Saddar", "Korangi",
)

# Mon–Fri, six 40-minute periods with a break after the third.
PERIODS = (
    (time(8, 0), time(8, 40)),
    (time(8, 40), time(9, 20)),
    (time(9, 20), time(10, 0)),
    (time(10, 30), time(11, 10)),
    (time(11, 10), time(11, 50)),
    (time(11, 50), time(12, 30)),
)
BREAK = (time(10, 0), time(10, 30))
SCHOOL_DAYS = range(5)

NOTICES = (
    ("Parent-teacher meeting", "The parent-teacher meeting will be held on Saturday from 9:00 AM to 12:00 PM. Parents are requested to attend."),
    ("Winter uniform", "Winter uniform becomes compulsory from 1st November. Sweaters must be navy blue."),
    ("Fee reminder", "Monthly fees are due by the 10th of every month. Please clear any dues to avoid a late fee."),
)

# Earlier versions of this command used dotted usernames; rename them in place
# so their existing attendance, homework and marks stay attached.
LEGACY_USERNAMES = {
    "demo.principal": "principal",
    "demo.teacher1": "teacher1",
    "demo.teacher2": "teacher2",
    "demo.teacher3": "teacher3",
    "demo.student": "student",
}


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
        rng = random.Random(42)
        today = timezone.localdate()
        year = self.active_year(today)
        self.rename_legacy_users(User)

        principal = self.demo_user(User, "principal", "Alex", "Principal", "principal")
        office = self.demo_user(User, "office", "Omar", "Office", "office")

        teachers = []
        for username, first_name, last_name, subject_name, code in TEACHERS:
            user = self.demo_user(User, username, first_name, last_name, "teacher")
            teacher, _ = Teacher.objects.get_or_create(user=user)
            subject, _ = Subject.objects.get_or_create(code=code, defaults={"name": subject_name})
            teachers.append((user, teacher, subject))

        names = [(first, last) for last in LAST_NAMES for first in FIRST_NAMES]
        rng.shuffle(names)
        # Keep the original ten demo students as the first class.
        names[:10] = [
            ("Ayaan", "Khan"), ("Areeba", "Ahmed"), ("Hamza", "Malik"), ("Zoya", "Sheikh"),
            ("Rayyan", "Ali"), ("Hania", "Hussain"), ("Ibrahim", "Qureshi"), ("Mishal", "Raza"),
            ("Saad", "Iqbal"), ("Noor", "Farooq"),
        ]

        in_session = year.start_date <= today <= year.end_date
        attendance_dates = self.school_days(today, year.start_date, ATTENDANCE_DAYS)
        all_students = []
        for class_index, (class_name, section) in enumerate(CLASSROOMS):
            classroom, _ = Classroom.objects.get_or_create(
                name=class_name, section=section, academic_year=year
            )
            for user, teacher, subject in teachers:
                TeacherAssignment.objects.get_or_create(
                    teacher=teacher, classroom=classroom, subject=subject
                )
            classroom.class_teacher = teachers[class_index % len(teachers)][1]
            classroom.save(update_fields=["class_teacher"])
            self.seed_timetable(classroom, class_index, teachers)
            self.seed_study_guides(classroom, teachers)
            Notification.objects.get_or_create(
                title=f"{class_name} {section} class test",
                classroom=classroom,
                defaults={
                    "message": "A short class test on this week's work will be held on Friday. Revise your notes.",
                    "created_by": classroom.class_teacher.user,
                },
            )

            students = []
            for offset in range(STUDENTS_PER_CLASS):
                number = class_index * STUDENTS_PER_CLASS + offset + 1
                first_name, last_name = names[number - 1]
                student, _ = Student.objects.update_or_create(
                    admission_number=f"DEMO-{number:03}",
                    defaults={
                        "first_name": first_name,
                        "last_name": last_name,
                        "date_of_birth": date(today.year - 11 - class_index // 2, rng.randint(1, 12), rng.randint(1, 28)),
                        "guardian_name": f"{rng.choice(FIRST_NAMES[::2])} {last_name}",
                        "guardian_phone": f"0300-{rng.randint(1000000, 9999999)}",
                        "gender": Student.Gender.FEMALE if first_name in FEMALE_NAMES else Student.Gender.MALE,
                        "cnic": f"42101-{rng.randint(1000000, 9999999)}-{rng.randint(1, 9)}",
                        "email": f"{first_name}.{last_name}{number}@example.com".lower(),
                        "phone": f"0312-{rng.randint(1000000, 9999999)}",
                        "address": f"House {rng.randint(1, 250)}, Street {rng.randint(1, 30)}",
                        "area": rng.choice(AREAS),
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
            all_students.extend(students)

            if in_session:
                self.seed_attendance(rng, students, attendance_dates, teachers[0][0])
                self.seed_homework(classroom, teachers, today)
                self.seed_exam(rng, year, classroom, students, teachers, today)
            self.seed_fees(rng, year, students, office, today)

        self.seed_staff_and_expenses(principal, office, teachers, today)

        for title, message in NOTICES:
            Notification.objects.get_or_create(
                title=title,
                classroom=None,
                defaults={"message": message, "created_by": principal},
            )

        student_user = self.demo_user(
            User,
            "student",
            all_students[0][0].first_name,
            all_students[0][0].last_name,
            "student",
        )
        Student.objects.filter(user=student_user).exclude(pk=all_students[0][0].pk).update(user=None)
        all_students[0][0].user = student_user
        all_students[0][0].save(update_fields=["user"])

        # A parent with two children (in different classes) to show the child switcher.
        parent_user = self.demo_user(User, "parent", "Imran", all_students[0][0].last_name, "parent")
        children = (all_students[0][0], all_students[STUDENTS_PER_CLASS][0])
        Student.objects.filter(guardian_user=parent_user).exclude(pk__in=[c.pk for c in children]).update(guardian_user=None)
        for child in children:
            child.guardian_user = parent_user
            child.save(update_fields=["guardian_user"])

        self.stdout.write(f"  Classes: {len(CLASSROOMS)} ({STUDENTS_PER_CLASS} students each)")
        self.stdout.write(f"  Students: {len(all_students)} fictional records")
        self.stdout.write("  Logins: principal, office, teacher1 to teacher6, student, parent")
        self.stdout.write("  Student login 'student' is linked to DEMO-001")

    @staticmethod
    def active_year(today):
        year = AcademicYear.objects.filter(is_active=True).first()
        if year is not None:
            return year
        year_start = today.year if today.month >= 8 else today.year - 1
        year, _ = AcademicYear.objects.get_or_create(
            name=f"{year_start}-{year_start + 1}",
            defaults={
                "start_date": date(year_start, 8, 1),
                "end_date": date(year_start + 1, 6, 30),
            },
        )
        year.is_active = True
        year.save(update_fields=["is_active"])
        return year

    @staticmethod
    def school_days(today, start, count):
        days = []
        day = today
        while len(days) < count and day >= start:
            if day.weekday() < 5:
                days.append(day)
            day -= timedelta(days=1)
        return days

    @staticmethod
    def rename_legacy_users(User):
        for old, new in LEGACY_USERNAMES.items():
            if not User.objects.filter(username=new).exists():
                User.objects.filter(username=old).update(username=new)

    @staticmethod
    def seed_timetable(classroom, class_index, teachers):
        for day in SCHOOL_DAYS:
            TimetableEntry.objects.get_or_create(
                classroom=classroom,
                day=day,
                start_time=BREAK[0],
                defaults={"end_time": BREAK[1], "label": "Break"},
            )
            for period, (start, end) in enumerate(PERIODS):
                if TimetableEntry.objects.filter(classroom=classroom, day=day, start_time=start).exists():
                    continue
                # Shifting by class and day keeps each teacher in one room per period.
                _user, teacher, subject = teachers[(period + class_index + day) % len(teachers)]
                entry = TimetableEntry(
                    classroom=classroom,
                    day=day,
                    start_time=start,
                    end_time=end,
                    subject=subject,
                    teacher=teacher,
                )
                entry.full_clean()
                entry.save()

    @staticmethod
    def seed_study_guides(classroom, teachers):
        for user, _teacher, subject in teachers[:4]:
            StudyGuide.objects.get_or_create(
                classroom=classroom,
                title=f"{subject.name} — Unit 1 notes",
                defaults={
                    "subject": subject,
                    "description": f"Key points and practice questions for the first {subject.name.lower()} unit.",
                    "uploaded_by": user,
                },
            )

    @staticmethod
    def seed_attendance(rng, students, dates, recorded_by):
        statuses = [AttendanceRecord.Status.PRESENT] * 8 + [
            AttendanceRecord.Status.LATE,
            AttendanceRecord.Status.ABSENT,
        ]
        for day in dates:
            for _student, enrollment in students:
                if AttendanceRecord.objects.filter(enrollment=enrollment, date=day).exists():
                    continue
                AttendanceRecord.objects.create(
                    enrollment=enrollment,
                    date=day,
                    status=rng.choice(statuses),
                    recorded_by=recorded_by,
                )

    @staticmethod
    def seed_homework(classroom, teachers, today):
        for index, (user, _teacher, subject) in enumerate(teachers, start=1):
            Homework.objects.update_or_create(
                classroom=classroom,
                subject=subject,
                assigned_by=user,
                title=f"Demo {subject.name} practice",
                defaults={
                    "description": f"Sample {subject.name.lower()} homework for {classroom.name} {classroom.section}.",
                    "assigned_date": today,
                    "due_date": today + timedelta(days=index + 2),
                },
            )

    @staticmethod
    def seed_exam(rng, year, classroom, students, teachers, today):
        exam, _ = Exam.objects.get_or_create(
            academic_year=year,
            classroom=classroom,
            name="Demo Midterm",
            defaults={"date": max(year.start_date, today - timedelta(days=5)), "results_published": True},
        )
        if not exam.results_published:
            exam.results_published = True
            exam.save(update_fields=["results_published"])
        for user, _teacher, subject in teachers:
            ExamSubject.objects.get_or_create(
                exam=exam, subject=subject, defaults={"maximum_marks": 100}
            )
            for student, _enrollment in students:
                if StudentMark.objects.filter(exam=exam, student=student, subject=subject).exists():
                    continue
                StudentMark.objects.create(
                    exam=exam,
                    student=student,
                    subject=subject,
                    marks_awarded=rng.randint(45, 98),
                    updated_by=user,
                )

    @staticmethod
    def seed_fees(rng, year, students, office, today):
        months = []
        month = date(year.start_date.year, year.start_date.month, 1)
        while month <= today and month <= year.end_date:
            months.append(month)
            month = date(month.year + month.month // 12, month.month % 12 + 1, 1)

        for student, enrollment in students:
            # Most students are fully paid; some owe for the latest month. Decided by
            # admission number (not the random generator) so reruns pick the same students.
            number = int(student.admission_number.rsplit("-", 1)[-1])
            paid_months = len(months) - (1 if number % 3 == 0 else 0)
            if number % 4 == 0 and months:
                # An unpaid activity charge this month, so dues show up even after reruns.
                FeeCharge.objects.get_or_create(
                    student=student,
                    enrollment=enrollment,
                    description=f"Sports & activity fund — {months[-1]:%B %Y}",
                    defaults={
                        "category": FeeCharge.Category.ACTIVITY,
                        "academic_year": year,
                        "amount": Decimal("1500.00"),
                        "due_date": min(today, months[-1] + timedelta(days=4)),
                        "created_by": office,
                    },
                )
            for index, month in enumerate(months):
                label = f"Tuition fee — {month:%B %Y}"
                FeeCharge.objects.get_or_create(
                    student=student,
                    enrollment=enrollment,
                    description=label,
                    defaults={
                        "category": FeeCharge.Category.MONTHLY,
                        "academic_year": year,
                        "amount": MONTHLY_FEE,
                        "due_date": month + timedelta(days=9),
                        "created_by": office,
                    },
                )
                if index < paid_months and not FeePayment.objects.filter(
                    student=student, notes=label
                ).exists():
                    FeePayment.objects.create(
                        student=student,
                        academic_year=year,
                        enrollment=enrollment,
                        amount=MONTHLY_FEE,
                        payment_date=min(today, month + timedelta(days=rng.randint(1, 9))),
                        method=rng.choice((FeePayment.Method.CASH, FeePayment.Method.BANK_TRANSFER)),
                        notes=label,
                        received_by=office,
                    )

    @staticmethod
    def seed_staff_and_expenses(principal, office, teachers, today):
        people = [
            (principal, "Principal", Decimal("120000.00")),
            (office, "Accountant", Decimal("45000.00")),
        ] + [(user, "Teacher", Decimal("55000.00")) for user, _teacher, _subject in teachers]
        staff = []
        for user, designation, salary in people:
            member, _ = StaffMember.objects.update_or_create(
                user=user,
                defaults={
                    "name": user.get_full_name() or user.username,
                    "designation": designation,
                    "monthly_salary": salary,
                    "is_active": True,
                },
            )
            staff.append(member)
        for name, designation, salary in SUPPORT_STAFF:
            member, _ = StaffMember.objects.update_or_create(
                name=name,
                user=None,
                defaults={"designation": designation, "monthly_salary": salary, "is_active": True},
            )
            staff.append(member)

        this_month = today.replace(day=1)
        last_month = (this_month - timedelta(days=1)).replace(day=1)
        # Last month is fully paid; this month only the support staff so far.
        for month, members in ((last_month, staff), (this_month, staff[-len(SUPPORT_STAFF):])):
            for member in members:
                Expense.objects.get_or_create(
                    staff=member,
                    salary_month=month,
                    defaults={
                        "category": Expense.Category.SALARY,
                        "description": f"Salary — {member.name} — {month:%B %Y}",
                        "amount": member.monthly_salary,
                        "date": min(today, month + timedelta(days=4)),
                        "recorded_by": office,
                    },
                )
        for month in (last_month, this_month):
            for category, description, amount, day in MONTHLY_EXPENSES:
                spent_on = month + timedelta(days=day - 1)
                if spent_on > today:
                    continue
                Expense.objects.get_or_create(
                    category=category,
                    description=f"{description} — {month:%B %Y}",
                    defaults={"amount": amount, "date": spent_on, "recorded_by": office},
                )

    @staticmethod
    def demo_user(User, username, first_name, last_name, role):
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.is_active = True
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user
