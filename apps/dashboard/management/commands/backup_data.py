"""Back up the school's data: run it every day (Task Scheduler / cron) and copy the
backups folder somewhere off the server (Google Drive, USB disk).

Restore with:  python manage.py loaddata backups/data-YYYYMMDD-HHMM.json.gz
"""

import gzip
import os
import shutil
import sqlite3
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

PREFIXES = ("data-", "db-", "media-")
EXCLUDE = ("contenttypes", "auth.permission", "sessions", "admin.logentry")


class Command(BaseCommand):
    help = "Save a copy of all school data (and uploaded photos/files) to the backups folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            default=os.environ.get("BACKUP_DIR") or str(settings.BASE_DIR / "backups"),
            help="Folder to write backups to (default: ./backups or $BACKUP_DIR).",
        )
        parser.add_argument("--keep-days", type=int, default=30, help="Delete backups older than this (0 keeps all).")

    def handle(self, *args, **options):
        folder = Path(options["dir"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        written = []

        data_file = folder / f"data-{stamp}.json.gz"
        with gzip.open(data_file, "wt", encoding="utf-8") as handle:
            call_command(
                "dumpdata",
                exclude=list(EXCLUDE),
                natural_foreign=True,
                natural_primary=True,
                indent=None,
                stdout=handle,
            )
        written.append(data_file)

        if connection.vendor == "sqlite":
            db_file = folder / f"db-{stamp}.sqlite3"
            source = sqlite3.connect(settings.DATABASES["default"]["NAME"])
            target = sqlite3.connect(db_file)
            with target:
                source.backup(target)
            source.close()
            target.close()
            written.append(db_file)

        media = Path(settings.MEDIA_ROOT)
        if media.is_dir() and any(media.iterdir()):
            archive = shutil.make_archive(str(folder / f"media-{stamp}"), "zip", media)
            written.append(Path(archive))

        removed = self._prune(folder, options["keep_days"])
        for path in written:
            self.stdout.write(f"  {path.name} ({path.stat().st_size / 1024:.0f} KB)")
        if removed:
            self.stdout.write(f"  Removed {removed} backup file(s) older than {options['keep_days']} days.")
        self.stdout.write(self.style.SUCCESS(f"Backup saved in {folder}"))

    @staticmethod
    def _prune(folder, keep_days):
        if keep_days <= 0:
            return 0
        cutoff = time.time() - keep_days * 86400
        removed = 0
        for path in folder.iterdir():
            if path.is_file() and path.name.startswith(PREFIXES) and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed
