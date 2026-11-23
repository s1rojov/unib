from django.core.management.base import BaseCommand

from vision.worker import Supervisor


class Command(BaseCommand):
    help = "Tahlil jarayonini (worker) ishga tushiradi"

    def handle(self, *args, **options):
        sup = Supervisor()
        sup.install_signals()
        sup.run_forever()
