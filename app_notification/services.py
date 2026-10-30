"""Process 7.0 - Manage Notifications (FR-17, FR-18).

Stock / order modules call these helpers; the alerts are stored in
NOTIFICATION (D10) and shown in the navbar bell and the notification page.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from app_accounts.models import User
from app_notification.models import Notification


def notify_users(users, type_, message, dedupe_prefix=None):
    """Create one notification per user. With dedupe_prefix an unread notification that
    starts with the same prefix suppresses a duplicate (avoids alert spam)."""
    created = []
    for user in users:
        if dedupe_prefix and Notification.objects.filter(
                user=user, type=type_, is_read=False, message__startswith=dedupe_prefix).exists():
            continue
        created.append(Notification.objects.create(user=user, type=type_, message=message[:255]))
    return created


def notify_roles(role_names, type_, message, dedupe_prefix=None):
    users = User.objects.filter(status='Active', role__role_name__in=role_names)
    return notify_users(users, type_, message, dedupe_prefix)


def notify_perm(codes, type_, message):
    from app_accounts.decorators import users_with_perm
    return notify_users(users_with_perm(*codes), type_, message)


def check_reorder(product):
    """FR-17: alert when total quantity on hand <= reorder level (DFD F37 -> Inventory Manager)."""
    from django.db.models import Sum
    from app_stock.models import Stock
    if product.reorder_level <= 0:
        return
    total = Stock.objects.filter(product=product).aggregate(t=Sum('quantity_on_hand'))['t'] or 0
    if total <= product.reorder_level:
        prefix = f'Low stock: {product.sku}'
        notify_roles(['Inventory Manager'], 'LOW_STOCK',
                     f'{prefix} - {product.name} has {total} {product.unit_of_measure} '
                     f'(reorder level {product.reorder_level})', dedupe_prefix=prefix)


def sync_expiry_alerts():
    """FR-18 / FR-16: EXPIRY alerts for batches expiring soon or already expired
    (DFD F38 -> Warehouse Staff). Safe to call repeatedly."""
    from app_stock.models import StockBatch
    limit = timezone.localdate() + timedelta(days=settings.EXPIRY_ALERT_DAYS)
    batches = StockBatch.objects.filter(quantity_on_hand__gt=0, expiry_date__isnull=False,
                                        expiry_date__lte=limit).select_related('product', 'warehouse')
    today = timezone.localdate()
    count = 0
    for b in batches:
        state = 'EXPIRED' if b.expiry_date < today else 'expires'
        prefix = f'Expiry: {b.product.sku} batch {b.batch_number}'
        count += len(notify_roles(
            ['Warehouse Staff'], 'EXPIRY',
            f'{prefix} {state} {b.expiry_date:%d-%m-%Y} ({b.quantity_on_hand} in {b.warehouse.name})',
            dedupe_prefix=prefix))
    return count
