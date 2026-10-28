import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.academics.models import Student


class BackupTests(TestCase):
    def test_backup_writes_restorable_data(self):
        Student.objects.create(admission_number="BK-1", first_name="Backup", last_name="Kid")
        with tempfile.TemporaryDirectory() as folder:
            call_command("backup_data", dir=folder, stdout=open(os.devnull, "w"))
            files = sorted(p.name for p in Path(folder).iterdir())
            data_file = next(Path(folder) / name for name in files if name.startswith("data-"))
            with gzip.open(data_file, "rt", encoding="utf-8") as handle:
                records = json.load(handle)
        self.assertTrue(any(r["model"] == "academics.student" and r["fields"]["admission_number"] == "BK-1" for r in records))
        self.assertFalse(any(r["model"] == "sessions.session" for r in records))


class ProtectedMediaTests(TestCase):
    def test_uploaded_files_need_a_login(self):
        with tempfile.TemporaryDirectory() as media:
            Path(media, "photo.txt").write_text("private")
            with override_settings(MEDIA_ROOT=media):
                self.assertEqual(self.client.get("/media/photo.txt").status_code, 302)
                self.client.force_login(get_user_model().objects.create_user(username="media-user", role="office"))
                response = self.client.get("/media/photo.txt")
                self.assertEqual(b"".join(response.streaming_content), b"private")
                self.assertIn(self.client.get("/media/../config/settings.py").status_code, (400, 404))


class LiveSettingsTests(TestCase):
    def _load_settings(self, **env):
        clean = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_")}
        clean.update(env)
        return subprocess.run(
            [sys.executable, "-c", "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; "
             "from django.conf import settings; print(settings.SESSION_COOKIE_SECURE, settings.SECURE_SSL_REDIRECT)"],
            cwd=settings.BASE_DIR, env=clean, capture_output=True, text=True,
        )

    def test_live_mode_refuses_the_demo_secret_key(self):
        result = self._load_settings(DJANGO_DEBUG="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", result.stderr)

    def test_live_mode_turns_on_https_protection(self):
        result = self._load_settings(DJANGO_DEBUG="false", DJANGO_SECRET_KEY="x" * 50)
        self.assertEqual(result.stdout.split(), ["True", "True"], result.stderr)
