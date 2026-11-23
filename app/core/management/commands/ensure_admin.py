import os

from django.core.management.base import BaseCommand

from core.models import RecognitionSettings, User


class Command(BaseCommand):
    help = "Birinchi ishga tushirishda administratorni yaratadi (INITIAL_ADMIN_* env)"

    def handle(self, *args, **options):
        RecognitionSettings.get()
        if User.objects.filter(role=User.Role.ADMIN).exists():
            return
        username = os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
        password = os.environ.get("INITIAL_ADMIN_PASSWORD")
        if not password:
            self.stderr.write("INITIAL_ADMIN_PASSWORD berilmagan — administrator yaratilmadi")
            return
        u = User(username=username, role=User.Role.ADMIN)
        u.set_password(password)
        u.save()
        self.stdout.write(f"Administrator yaratildi: {username}")
