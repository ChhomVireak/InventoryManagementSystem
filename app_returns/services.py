"""Returns (FR-15): purchase returns leave stock, sales returns re-enter it when restockable."""
from django.db import transaction
from django.db.models import Sum

from app_accounts import audit
from app_backend.utils import next_number
from app_notification.services import notify_users
from app_purchase.models import PurchaseOrder
from app_returns.models import Return, ReturnItem
from app_sales.models import SalesOrder
from app_stock import services as stock
from app_stock.models import StockTransactionLine
from app_stock.services import StockError


def find_order(return_type, number):
    number = (number or '').strip()
    if return_type == 'PURCHASE_RETURN':
        return PurchaseOrder.objects.filter(po_number__iexact=number).first()
    return SalesOrder.objects.filter(so_number__iexact=number).first()


def returnable_items(return_type, order):
    """[(order_item, already_returned, returnable)] - only goods that actually moved can be returned."""
    rows = []
    purchase = return_type == 'PURCHASE_RETURN'
    for item in order.items.select_related('product'):
        moved = item.quantity_received if purchase else item.quantity_shipped
        used = (ReturnItem.objects.filter(return_order__return_type=return_type,
                                          return_order__reference_order_id=order.pk, product=item.product)
                .exclude(return_order__status='Cancelled').aggregate(t=Sum('quantity'))['t'] or 0)
        rows.append((item, used, max(moved - used, 0)))
    return rows


@transaction.atomic
def create_return(*, user, return_type, order, return_date, reason, entries, request):
    """entries: [(order_item, quantity, condition)] - validated against what can still be returned."""
    reason = (reason or '').strip()
    if not reason:
        raise StockError('A reason is required.')
    allowed = {item.pk: (item, left) for item, _used, left in returnable_items(return_type, order)}
    chosen = []
    for item, qty, condition in entries:
        if qty <= 0:
            continue
        if qty > allowed[item.pk][1]:
            raise StockError(f'{item.product.sku}: only {allowed[item.pk][1]} can still be returned.')
        chosen.append((item, qty, condition))
    if not chosen:
        raise StockError('Enter a return quantity for at least one product.')
    ret = Return.objects.create(
        return_number=next_number(Return, 'return_number', 'RT'), return_type=return_type,
        reference_order_type='PURCHASE_ORDER' if return_type == 'PURCHASE_RETURN' else 'SALES_ORDER',
        reference_order_id=order.pk, created_by=user, return_date=return_date, reason=reason)
    for item, qty, condition in chosen:
        ReturnItem.objects.create(return_order=ret, product=item.product, quantity=qty, condition=condition,
                                  unit_price=item.unit_price)
    audit.log_obj(request, 'CREATE', ret, user=user)
    from app_accounts.decorators import users_with_perm
    notify_users(users_with_perm('stock.adjust.approve'), 'APPROVAL', f'Approval needed: return {ret.return_number}')
    return ret


@transaction.atomic
def approve_return(ret, *, approver, request):
    ret = Return.objects.select_for_update().get(pk=ret.pk)
    if ret.status != 'Pending':
        raise StockError('Only pending returns can be approved.')
    ret.status = 'Approved'
    ret.save(update_fields=['status'])
    audit.log_obj(request, 'APPROVE', ret, user=approver)
    notify_users([ret.created_by], 'APPROVAL', f'Return {ret.return_number} was approved')
    return ret


@transaction.atomic
def cancel_return(ret, *, user, request):
    ret = Return.objects.select_for_update().get(pk=ret.pk)
    if ret.status not in ('Pending', 'Approved'):
        raise StockError('This return can no longer be cancelled.')
    ret.status = 'Cancelled'
    ret.save(update_fields=['status'])
    audit.log_obj(request, 'CANCEL', ret, user=user)
    return ret


@transaction.atomic
def complete_return(ret, *, warehouse, user, request):
    ret = Return.objects.select_for_update().get(pk=ret.pk)
    if ret.status != 'Approved':
        raise StockError('A return must be approved before it is completed.')
    items = list(ret.items.select_related('product'))
    if ret.return_type == 'PURCHASE_RETURN':
        # goods go back to the supplier - expired stock may be returned too
        stock.record_out(warehouse=warehouse, user=user, transaction_type='RETURN_OUT', reference_type='RETURN',
                         reference_id=ret.pk, notes=ret.return_number, allow_expired=True,
                         lines=[{'product': i.product, 'quantity': i.quantity, 'unit_cost': i.unit_price}
                                for i in items])
    else:
        lines = []
        for i in items:
            if i.condition != 'Restockable':
                continue          # damaged goods are recorded on the return but never re-enter stock
            line = {'product': i.product, 'quantity': i.quantity, 'unit_cost': i.unit_price}
            if i.product.tracks_batches:
                origin = (StockTransactionLine.objects.filter(
                    transaction__reference_type='SO', transaction__reference_id=ret.reference_order_id,
                    product=i.product, batch__isnull=False).select_related('batch').first())
                if origin is None:
                    raise StockError(f'{i.product.sku}: original batch not found - mark the item as Damaged '
                                     f'or use a stock adjustment.')
                line.update(batch_number=origin.batch.batch_number, expiry_date=origin.batch.expiry_date)
            lines.append(line)
        if lines:
            stock.record_in(warehouse=warehouse, user=user, transaction_type='RETURN_IN', reference_type='RETURN',
                            reference_id=ret.pk, notes=ret.return_number, lines=lines, enforce_tracking=False)
    ret.status = 'Completed'
    ret.save(update_fields=['status'])
    audit.log_obj(request, 'COMPLETE', ret, user=user)
    notify_users([ret.created_by], 'ORDER_STATUS', f'Return {ret.return_number} completed')
    return ret
