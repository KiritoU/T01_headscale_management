from django.core.management.base import BaseCommand

from gateways.monitoring_service import run_monitor_scheduler


class Command(BaseCommand):
    help = "Enqueue due gateway monitor discovery scans"

    def handle(self, *args, **options):
        scheduled = run_monitor_scheduler()
        self.stdout.write(self.style.SUCCESS(f"Scheduled {scheduled} monitor scan(s)"))
