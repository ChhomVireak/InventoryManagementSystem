from django.core.management.base import BaseCommand

from app_notification.services import check_reorder, sync_expiry_alerts
from app_stock.services import low_stock_products


class Command(BaseCommand):
    help = 'Generate low-stock and expiry notifications (run daily from cron).'

    def handle(self, *args, **options):
        for product in low_stock_products():
            check_reorder(product)
        created = sync_expiry_alerts()
        self.stdout.write(self.style.SUCCESS(f'Alerts checked. {created} new expiry notification(s).'))
