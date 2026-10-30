"""Process 3.0 - Manage Purchasing (FR-11, FR-12)."""
from datetime import date

from django.db import transaction
from django.utils import timezone

from app_accounts import audit
from app_backend.utils import next_number
from app_notification.services import notify_users
from app_purchase.models import PurchaseOrder, PurchaseOrderItem
from app_stock import services as stock
from app_stock.services import StockError


@transaction.atomic
def save_order(*, form, rows, user, request, order=None):
    po = form.save(commit=False)
    creating = order is None
    if creating:
        po.created_by = user
        po.po_number = next_number(PurchaseOrder, 'po_number', 'PO')
        po.status = 'Draft'
    old = None if creating else audit.snapshot(order)
    po.save()
    po.items.all().delete()
    for r in rows:
        PurchaseOrderItem.objects.create(po=po, product=r['product'], quantity_ordered=r['quantity'],
                                         unit_price=r['price'])
    po.recalculate()
    audit.log_obj(request, 'CREATE' if creating else 'UPDATE', po, old=old, user=user)
    return po


@transaction.atomic
def set_status(po, new_status, *, user, request, allowed_from):
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status not in allowed_from:
        raise StockError(f'A {po.status} purchase order cannot be changed to {new_status}.')
    if new_status == 'Cancelled' and po.items.filter(quantity_received__gt=0).exists():
        raise StockError('Goods were already received - use a purchase return instead of cancelling.')
    old = audit.snapshot(po)
    po.status = new_status
    po.save(update_fields=['status'])
    audit.log_obj(request, {'Sent': 'APPROVE', 'Cancelled': 'CANCEL'}.get(new_status, 'UPDATE'), po, old=old,
                  user=user)
    if po.created_by_id != user.pk:
        notify_users([po.created_by], 'ORDER_STATUS', f'{po.po_number} is now {new_status}')
    return po


@transaction.atomic
def receive_goods(po, *, warehouse, user, receipts, request):
    """receipts: {po_item_id: {'qty', 'batch_number', 'expiry_date'}}
    FR-12: update stock AND PO status in one transaction."""
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status not in ('Sent', 'Partial'):
        raise StockError('Only approved (Sent) or partially received orders can receive goods.')
    items = {i.pk: i for i in po.items.select_related('product').select_for_update(of=('self',))}
    lines = []
    for item_id, r in receipts.items():
        qty = r['qty']
        if qty <= 0:
            continue
        item = items[item_id]
        if qty > item.remaining:
            raise StockError(f'{item.product.sku}: cannot receive {qty}; only {item.remaining} still expected.')
        lines.append({'product': item.product, 'quantity': qty, 'batch_number': r.get('batch_number'),
                      'expiry_date': r.get('expiry_date'), 'unit_cost': item.unit_price})
        item.quantity_received += qty
        item.save()
    if not lines:
        raise StockError('Enter a quantity to receive for at least one product.')
    stock.record_in(warehouse=warehouse, user=user, lines=lines, reference_type='PO', reference_id=po.pk,
                    notes=po.po_number)
    fully = all(i.quantity_received >= i.quantity_ordered for i in po.items.all())
    po.status = 'Received' if fully else 'Partial'
    po.save(update_fields=['status'])
    audit.log_obj(request, 'RECEIVE', po, user=user)
    if po.created_by_id != user.pk:
        notify_users([po.created_by], 'ORDER_STATUS', f'{po.po_number} is now {po.status}')
    return po
