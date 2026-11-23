import time

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class Command(BaseCommand):
    help = "Baza tayyor va barcha migratsiyalar qo'llanguncha kutadi"

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=int, default=300)

    def handle(self, *args, **options):
        deadline = time.monotonic() + options["timeout"]
        while True:
            try:
                connection.ensure_connection()
                executor = MigrationExecutor(connection)
                if not executor.migration_plan(executor.loader.graph.leaf_nodes()):
                    self.stdout.write("Migratsiyalar tayyor")
                    return
            except Exception:
                pass
            finally:
                connection.close()
            if time.monotonic() > deadline:
                raise SystemExit("Migratsiyalarni kutish vaqti tugadi")
            time.sleep(2)
