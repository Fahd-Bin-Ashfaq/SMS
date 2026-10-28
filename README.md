# School Management System

A responsive web application for a school with approximately 500 students, 20 teachers, and one principal. The first release is an MVP for staff use; it is not a full accounting package or a student/parent portal.

## Technology

- Python 3.12+
- Django 5.2
- PostgreSQL in production; SQLite may be used for local development and tests
- Django templates, Bootstrap 5, and small amounts of vanilla JavaScript
- Django's built-in authentication with role-based permissions

Use free development tools and a free/locally hosted deployment where practical. Free hosting is not a production availability guarantee: before live use, configure reliable backups, HTTPS, access controls, and a recovery process. Never put real student data in a public demo environment.

## Roles

- **Principal:** school-wide access to records, reports, and dashboards.
- **Teacher:** access only to assigned classes and the academic records they manage.
- **Office staff:** student/class administration and fee records.

Enforce permissions on the server for every view and action; hiding a button is not authorization. Keep an audit trail for important changes to attendance, marks, and fee payments.

## MVP modules

1. **Accounts and permissions** — staff sign-in, role management, password reset, and access control.
2. **Academic setup** — students, teachers, academic years, classes/sections, subjects, and teacher-to-class assignments.
3. **Attendance** — daily class attendance, duplicate prevention, correction history, and class/month summaries.
4. **Exams and marks** — exam setup, subject marks, validation against maximum marks, and student/class result sheets.
5. **Homework** — class/subject homework with assigned/due dates and completion tracking.
6. **Fees** — student fee plans/charges, payments, receipts, and outstanding balances. This is school fee tracking, not general ledger accounting.
7. **Principal dashboard and reports** — school-wide attendance, academic, homework, and fee summaries with filters and printable reports.

## Shared data and integration contracts

- Use `DecimalField` for money and marks; never use floating-point values for fees.
- Use `DateField` for school dates and store timestamps as timezone-aware values.
- Every school record belongs to an academic year where applicable.
- Accounts owns the custom `User` model with a `role` value of `principal`, `teacher`, or `office`. Academic setup owns canonical `AcademicYear`, `Student`, `Enrollment`, `Teacher`, `Classroom`, `Subject`, and `TeacherAssignment` models. Other modules reference these models with foreign keys; do not create duplicate student, teacher, or class models.
- `Student` has `admission_number`, `first_name`, `last_name`, optional `date_of_birth`, optional guardian name/phone, and `is_active`. `Enrollment` links a student to a classroom and academic year; modules should use active enrollments when resolving the student's class for that year.
- `AcademicYear` has a name, start/end dates, and an active flag. `Classroom` has a name and section within an academic year. `Teacher` links one-to-one to the custom user. `Subject` has a name and code. `TeacherAssignment` links one teacher, classroom, and subject.
- Keep the app labels and Django app configs aligned with `config/settings.py`: `accounts`, `academics`, `attendance`, `assessments`, `homework`, `fees`, and `dashboard`.
- Attendance owns one record per student per class per date, with a controlled status such as present, absent, or late.
- Marks belong to an exam, student, and subject; validate that awarded marks do not exceed the exam's maximum.
- Homework belongs to a class and subject and may be assigned by a teacher who is assigned to that class.
- Fee charges and payments belong to a student; record payment date, amount, method, and receipt reference. Corrections must retain an audit history.
- Prefer Django `TextChoices`, model validation, database constraints, and migrations over unvalidated free-form values.
- Use Django messages/forms for actionable errors. Do not silently ignore invalid input.

## Suggested project layout

```text
config/                 Django project settings and URL configuration
apps/
  accounts/             staff accounts, roles, and permissions
  academics/            students, staff links, classes, subjects, assignments
  attendance/           attendance records and reports
  assessments/          exams and marks
  homework/             homework and completion tracking
  fees/                 charges, payments, and receipts
  dashboard/             principal dashboard and cross-module reports
templates/
static/
```

Each app should own its models, forms, views, URLs, admin configuration, migrations, and focused tests. Cross-app imports should use the canonical academic models and shared account model. Keep UI and permission checks consistent across HTML views and any future API.

## Delivery sequence

1. Agree on the shared model and permission contracts in this document.
2. Create the Django project scaffold and shared settings.
3. Implement accounts and academic setup, then implement attendance, assessments, homework, and fees in parallel against those contracts.
4. Integrate the principal dashboard after the module data/query interfaces exist.
5. Run migrations and tests; verify teacher access boundaries and calculations with representative records.
6. Deploy with HTTPS, secure secrets, scheduled database backups, restore testing, and staff training.

## Local development

From the project directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The initial principal can be created as a superuser, then assigned the `principal` role by an administrator. Set a unique `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, and appropriate `DJANGO_ALLOWED_HOSTS` in production. Set `DB_ENGINE=postgresql` and the `POSTGRES_*` variables to use PostgreSQL; otherwise Django uses a local SQLite database.

### Local client demo

With the development server stopped or in another terminal, run:

```powershell
python manage.py seed_demo_data
```

This command is restricted to `DEBUG=true` and creates fictional demo records: 5 classes with 10 students each, 6 subject teachers (one is class teacher of each class), a Mon–Fri timetable, principal, office and student logins, two weeks of attendance, homework, sample marks, monthly tuition fees with payments, study guides and notifications. It can be rerun to refresh the demo accounts and records.

All demo accounts use the same local-only password, `1234`:

| Role | Username |
| --- | --- |
| Principal | `principal` |
| Office staff | `office` |
| Teacher | `teacher1` … `teacher6` (`teacher1` is class teacher of Grade 6 A) |
| Student | `student` |
| Parent | `parent` (two children, switch between them in the sidebar) |

### Student portal

Students are sent to `/portal/` after signing in. It has Home (next period, attendance), Classroom (weekly timetable, homework, results), Study Guides, Balance (month-by-month fees for the session), ID Card, Profile and Notifications, with light and dark themes. Study guides and notifications are added from the Django admin.

Timetables are managed at `/academics/timetable/`: principals can edit every class, a class teacher can edit their own class, and other staff can view. Set `SCHOOL_NAME`, `SCHOOL_CAMPUS` and `SCHOOL_CONTACT` to change what the portal and ID card show.

Do not use demo credentials or fictional sample data in a production deployment. The student account only sees its linked student profile and its own attendance/results.

Run tests with `python manage.py test`. Generate app migrations after model integration with `python manage.py makemigrations` and apply them with `python manage.py migrate`. Review generated migrations before deployment.

### Running a real school

- **School logo:** put `logo.png` (or `.jpg`/`.svg`) in `static/school/`. It shows on the sidebar, login page, fee receipts and ID cards. Set `SCHOOL_NAME`, `SCHOOL_CAMPUS` and `SCHOOL_CONTACT` for the receipt header.
- **Add students in bulk:** Students → *Import from Excel*. Download the template, fill one student per row and upload `.xlsx` or `.csv`. If any row has a problem nothing is saved and every problem is listed by row number.
- **Monthly fees:** Fees → *Add monthly fee* bills one month's tuition to every active student, with a fee per class. Students already billed for that month are skipped.
- **Receipts:** each payment prints on A4 as a parent copy and a school copy, with the amount in words and the remaining balance.
- **Parent logins:** Students → *Parent logins* creates a login whose username is the guardian's phone number and shares the password on WhatsApp. Brothers and sisters with the same guardian phone share one login.
- **Homework checking:** teachers use *Check work* on a homework to mark each student done or not done; students and parents see it in the portal.
- **New academic year:** create the next year under Academic years, then (as principal) *Promote students to next year*: copy the classes, confirm where each class goes, tick students who repeat a grade, and the top class leaves school.
- **Fee concessions, late fees and other charges:** the principal sets a % concession on a student's fee account (sibling, staff child, need-based); monthly fees apply it automatically. Fees → *Charge classes* adds admission fee, annual fund or exam fee to whole classes; *Late fee* fines students whose monthly fee is past due and unpaid (once per month).
- **Daily cash report:** Fees → *Today's cash* lists every receipt of a day by payment method and by who received it, with expenses and a signature line for printing. *Print list* on the Fees page prints the defaulters list.
- **Exams:** the principal uses *Create exam* (one name, many classes; subjects come from teacher assignments), then sets the *Date sheet* (can copy the same dates to all classes). Teachers enter a whole class's marks per subject. *Result cards* show total, percentage, grade, pass/fail (33% per subject) and class position; the class teacher writes remarks; the principal *publishes* results so students and parents can see and print them.
- **Absent alerts:** Attendance → *Send absent alerts to parents* lists the day's absent and late students with a WhatsApp button for each guardian.
- **Notice board:** principal and office post notices to the whole school or one class; teachers to their own classes. They appear under Notifications in the student/parent portal.
- **Staff attendance and salary slips:** Staff → *Staff attendance* each day (present, absent, late, leave). *Pay salary* suggests a deduction of one day's pay (salary ÷ 30) per absence and recovers any advance given from the Staff page, then prints a salary slip.

## Going live

1. **Server:** any host that runs Python/Django (for example PythonAnywhere, a VPS, or a school computer behind a tunnel). Install with `pip install -r requirements.txt`.
2. **Settings:** copy `.env.example` to `.env` and fill it in. With `DJANGO_DEBUG=false` the site refuses to start without a long random `DJANGO_SECRET_KEY`, forces HTTPS, uses secure cookies and signs people out after 8 hours.
3. **Database and files:** run `python manage.py migrate` and `python manage.py collectstatic --noinput`. Uploaded photos and study files are served only to signed-in users.
4. **First accounts:** `python manage.py createsuperuser`, then set its role to Principal in `/admin/`. Never run `seed_demo_data` on the live server and never use the demo passwords.
5. **Backups (every day):** `python manage.py backup_data` writes `backups/data-*.json.gz` (all records), a copy of the SQLite file and a zip of uploaded files, and deletes backups older than 30 days. Schedule it with Windows Task Scheduler or cron, and **copy the backups folder off the server** (Google Drive, USB disk) — a backup on the same machine is lost with it.
6. **Restore test (once a month):** on another computer, `python manage.py migrate` then `python manage.py loaddata backups/data-YYYYMMDD-HHMM.json.gz` and check a few students and fees.
