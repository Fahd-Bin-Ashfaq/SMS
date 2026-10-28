from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TeacherAssignment
from apps.assessments.models import Exam, ExamSubject, ResultRemark, StudentMark
from apps.assessments.results import class_results, grade_for

User = get_user_model()


class ExamToolsTests(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.year = AcademicYear.objects.create(
            name="Exam year", start_date=today - timedelta(days=90), end_date=today + timedelta(days=200), is_active=True
        )
        self.class_a = Classroom.objects.create(name="Grade 6", section="A", academic_year=self.year)
        self.class_b = Classroom.objects.create(name="Grade 6", section="B", academic_year=self.year)
        self.math = Subject.objects.create(name="Math", code="MX")
        self.eng = Subject.objects.create(name="English", code="EX")
        self.teacher_user = User.objects.create_user(username="exam-teacher", role="teacher")
        teacher = Teacher.objects.create(user=self.teacher_user)
        self.class_a.class_teacher = teacher
        self.class_a.save()
        for classroom in (self.class_a, self.class_b):
            TeacherAssignment.objects.create(teacher=teacher, classroom=classroom, subject=self.math)
        other = Teacher.objects.create(user=User.objects.create_user(username="eng-teacher", role="teacher"))
        TeacherAssignment.objects.create(teacher=other, classroom=self.class_a, subject=self.eng)
        self.students = []
        for name in ("Ali", "Sara", "Zain"):
            student = Student.objects.create(admission_number=f"E-{name}", first_name=name, last_name="K")
            Enrollment.objects.create(student=student, classroom=self.class_a, academic_year=self.year)
            self.students.append(student)
        self.principal = User.objects.create_user(username="exam-principal", role="principal")

    def _create_exam(self):
        self.client.force_login(self.principal)
        self.client.post(
            reverse("assessments:exam-create"),
            {"name": "Mid-term", "classrooms": [self.class_a.pk, self.class_b.pk], "maximum_marks": "50"},
        )
        return Exam.objects.get(classroom=self.class_a, name="Mid-term")

    def test_principal_creates_exam_for_many_classes_with_their_subjects(self):
        exam = self._create_exam()
        self.assertEqual(Exam.objects.filter(name="Mid-term").count(), 2)
        self.assertEqual(
            set(exam.subjects.values_list("subject__name", "maximum_marks")),
            {("Math", Decimal("50.00")), ("English", Decimal("50.00"))},
        )
        self.assertEqual(Exam.objects.get(classroom=self.class_b).subjects.count(), 1)

    def test_date_sheet_saves_and_copies_to_other_classes(self):
        exam = self._create_exam()
        math_paper = exam.subjects.get(subject=self.math)
        eng_paper = exam.subjects.get(subject=self.eng)
        self.client.post(
            reverse("assessments:date-sheet", args=[exam.pk]),
            {
                f"s{math_paper.pk}_date": "2026-11-10", f"s{math_paper.pk}_start": "09:00", f"s{math_paper.pk}_end": "11:00", f"s{math_paper.pk}_max": "60",
                f"s{eng_paper.pk}_date": "2026-11-11", f"s{eng_paper.pk}_start": "", f"s{eng_paper.pk}_end": "", f"s{eng_paper.pk}_max": "50",
                "copy": "1",
            },
        )
        math_paper.refresh_from_db()
        self.assertEqual((math_paper.paper_date, math_paper.maximum_marks), (date(2026, 11, 10), Decimal("60")))
        other = ExamSubject.objects.get(exam__classroom=self.class_b, subject=self.math)
        self.assertEqual(other.paper_date, date(2026, 11, 10))
        self.assertEqual(other.maximum_marks, Decimal("50"))

    def test_teacher_enters_marks_for_the_whole_class_only_for_own_subject(self):
        exam = self._create_exam()
        self.client.force_login(self.teacher_user)
        url = reverse("assessments:class-marks", args=[exam.pk, self.math.pk])
        response = self.client.post(url, {f"marks_{self.students[0].pk}": "60"})
        self.assertContains(response, "Enter a number from 0 to 50")
        self.assertFalse(StudentMark.objects.exists())
        self.client.post(url, {f"marks_{self.students[0].pk}": "45", f"marks_{self.students[1].pk}": "30"})
        self.assertEqual(StudentMark.objects.filter(exam=exam).count(), 2)
        self.assertEqual(
            self.client.post(reverse("assessments:class-marks", args=[exam.pk, self.eng.pk]), {}).status_code, 403
        )

    def test_result_cards_rank_grade_and_pass(self):
        exam = self._create_exam()
        marks = {"Ali": (45, 40), "Sara": (45, 40), "Zain": (10, 50)}
        for student in self.students:
            for subject, value in zip((self.math, self.eng), marks[student.first_name]):
                StudentMark.objects.create(exam=exam, student=student, subject=subject, marks_awarded=value)
        rows = {row["student"].first_name: row for row in class_results(exam)["rows"]}
        self.assertEqual((rows["Ali"]["position"], rows["Sara"]["position"], rows["Zain"]["position"]), (1, 1, 3))
        self.assertEqual((rows["Ali"]["percent"], rows["Ali"]["grade"], rows["Ali"]["passed"]), (Decimal("85.0"), "A", True))
        self.assertFalse(rows["Zain"]["passed"])  # 10/50 in Math is below 33%
        self.assertEqual(grade_for(Decimal("32.9")), "F")

    def test_class_teacher_writes_remarks_and_principal_publishes(self):
        exam = self._create_exam()
        self.client.force_login(self.teacher_user)
        self.client.post(reverse("assessments:result-cards", args=[exam.pk]), {f"remark_{self.students[0].pk}": "Very good"})
        self.assertEqual(ResultRemark.objects.get(student=self.students[0]).remarks, "Very good")
        self.client.post(reverse("assessments:result-cards", args=[exam.pk]), {"action": "publish", "publish": "1"})
        exam.refresh_from_db()
        self.assertFalse(exam.results_published)
        self.client.force_login(self.principal)
        self.client.post(reverse("assessments:result-cards", args=[exam.pk]), {"action": "publish", "publish": "1"})
        exam.refresh_from_db()
        self.assertTrue(exam.results_published)

    def test_students_see_only_published_cards_and_upcoming_papers(self):
        exam = self._create_exam()
        ExamSubject.objects.filter(exam=exam, subject=self.math).update(paper_date=timezone.localdate() + timedelta(days=3))
        user = User.objects.create_user(username="exam-student", role="student")
        self.students[0].user = user
        self.students[0].save()
        self.client.force_login(user)
        page = self.client.get(reverse("student_portal:exams"))
        self.assertEqual([p.subject for p in page.context["papers"]], [self.math])
        self.assertEqual(page.context["published"], [])
        self.assertEqual(self.client.get(reverse("student_portal:result_card", args=[exam.pk])).status_code, 404)
        exam.results_published = True
        exam.save()
        card = self.client.get(reverse("student_portal:result_card", args=[exam.pk]))
        self.assertEqual(card.status_code, 200)
        self.assertEqual(card.context["row"]["student"], self.students[0])

    def test_only_principal_creates_exams(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse("assessments:exam-create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("assessments:index")).status_code, 200)
