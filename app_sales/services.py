"""Process 4.0 - Manage Sales (FR-13, FR-14)."""
from django.db import transaction

from app_accounts import audit
from app_backend.utils import next_number
from app_notification.services import notify_users
from app_sales.models import SalesOrder, SalesOrderItem
from app_stock import services as stock
from app_stock.services import StockError


@transaction.atomic
def save_order(*, form, rows, user, request, order=None):
    so = form.save(commit=False)
    creating = order is None
    if creating:
        so.created_by = user
        so.so_number = next_number(SalesOrder, 'so_number', 'SO')
        so.status = 'Draft'
    old = None if creating else audit.snapshot(order)
    so.save()
    so.items.all().delete()
    for r in rows:
        SalesOrderItem.objects.create(so=so, product=r['product'], quantity_ordered=r['quantity'],
                                      unit_price=r['price'])
    so.recalculate()
    audit.log_obj(request, 'CREATE' if creating else 'UPDATE', so, old=old, user=user)
    return so


@transaction.atomic
def set_status(so, new_status, *, user, request, allowed_from):
    so = SalesOrder.objects.select_for_update().get(pk=so.pk)
    if so.status not in allowed_from:
        raise StockError(f'A {so.status} sales order cannot be changed to {new_status}.')
    if new_status == 'Cancelled' and so.items.filter(quantity_shipped__gt=0).exists():
        raise StockError('Goods were already shipped - use a sales return instead of cancelling.')
    old = audit.snapshot(so)
    so.status = new_status
    so.save(update_fields=['status'])
    audit.log_obj(request, {'Confirmed': 'APPROVE', 'Cancelled': 'CANCEL'}.get(new_status, 'UPDATE'), so,
                  old=old, user=user)
    if so.created_by_id != user.pk:
        notify_users([so.created_by], 'ORDER_STATUS', f'{so.so_number} is now {new_status}')
    return so


@transaction.atomic
def dispatch(so, *, warehouse, user, quantities, request):
    """FR-14: reduce stock (FEFO, never expired batches) and update SO status atomically.
    quantities: {so_item_id: qty}"""
    so = SalesOrder.objects.select_for_update().get(pk=so.pk)
    if so.status != 'Confirmed':
        raise StockError('Only confirmed orders can be dispatched.')
    items = {i.pk: i for i in so.items.select_related('product').select_for_update(of=('self',))}
    lines = []
    for item_id, qty in quantities.items():
        if qty <= 0:
            continue
        item = items[item_id]
        if qty > item.remaining:
            raise StockError(f'{item.product.sku}: cannot ship {qty}; only {item.remaining} remaining on the order.')
        lines.append({'product': item.product, 'quantity': qty, 'unit_cost': None})
        item.quantity_shipped += qty
        item.save()
    if not lines:
        raise StockError('Enter a quantity to ship for at least one product.')
    stock.record_out(warehouse=warehouse, user=user, lines=lines, reference_type='SO', reference_id=so.pk,
                     notes=so.so_number)          # raises StockError when stock is insufficient / expired
    if all(i.quantity_shipped >= i.quantity_ordered for i in so.items.all()):
        so.status = 'Shipped'
        so.save(update_fields=['status'])
    audit.log_obj(request, 'DISPATCH', so, user=user)
    if so.created_by_id != user.pk:
        notify_users([so.created_by], 'ORDER_STATUS', f'{so.so_number}: goods dispatched ({so.status})')
    return so
