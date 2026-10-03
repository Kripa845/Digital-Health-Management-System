from django.core.management.base import BaseCommand

from apps.lab_reports.services.upload import purge_stale_previews


class Command(BaseCommand):
    help = ('Delete lab report previews that were never confirmed or saved (and their encrypted files) '
            'after 24 hours. Run it daily.')

    def handle(self, *args, **options):
        count = purge_stale_previews()
        self.stdout.write(self.style.SUCCESS(f'Deleted {count} unconfirmed lab report upload(s).'))
