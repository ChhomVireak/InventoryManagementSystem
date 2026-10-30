"""Process 2.0 - Manage Stock: the single place where stock quantities change.

Every movement:
  * runs inside one database transaction (all or nothing),
  * locks the stock / batch rows with SELECT ... FOR UPDATE so concurrent
    updates cannot lose data or double-count (NFR-15, risk R-07),
  * writes an immutable ledger entry (StockTransaction + lines) (O2, FR-06/07),
  * enforces the business rules: no negative stock, batch/expiry data required,
    no dispatch of expired batches (FR-07, FR-16, R-08),
  * triggers the reorder check (FR-17).
"""
from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from app_accounts import audit
from app_accounts.decorators import users_with_perm
from app_notification.services import check_reorder, notify_users
from app_stock.models import (Stock, StockAdjustment, StockBatch, StockCount, StockCountItem, StockTransaction,
                              StockTransactionLine, StockTransfer, StockTransferItem)
from app_backend.utils import next_number


class StockError(Exception):
    """A business-rule violation; the message is safe to show to the user."""


# ------------------------------------------------------------------ low level
def _locked_stock(product, warehouse):
    stock, _ = Stock.objects.get_or_create(product=product, warehouse=warehouse)
    return Stock.objects.select_for_update().get(pk=stock.pk)


def _new_transaction(type_, warehouse, user, reference_type, reference_id, notes):
    return StockTransaction.objects.create(
        transaction_type=type_, warehouse=warehouse, user=user, reference_type=reference_type,
        reference_id=reference_id, notes=(notes or '')[:255])


def _add(txn, product, warehouse, quantity, *, batch_number=None, expiry_date=None, unit_cost=None,
         enforce_tracking=True):
    if quantity <= 0:
        raise StockError('Quantity must be greater than zero.')
    stock = _locked_stock(product, warehouse)
    batch = None
    if product.tracks_batches:
        if not batch_number:
            if enforce_tracking:
                raise StockError(f'{product.sku}: batch number is required for this product.')
            batch_number = f'UNBATCHED-{txn.pk}'
        if product.is_expiry_tracked and enforce_tracking and not expiry_date:
            raise StockError(f'{product.sku}: expiry date is required for this product.')
        if expiry_date and expiry_date < timezone.localdate():
            raise StockError(f'{product.sku}: expiry date {expiry_date:%d-%m-%Y} is in the past.')
        batch, created = StockBatch.objects.get_or_create(
            product=product, warehouse=warehouse, batch_number=batch_number,
            defaults={'expiry_date': expiry_date, 'quantity_on_hand': 0})
        batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
        if not created and expiry_date and batch.expiry_date and batch.expiry_date != expiry_date:
            raise StockError(f'{product.sku}: batch {batch_number} already exists with expiry '
                             f'{batch.expiry_date:%d-%m-%Y}.')
        if not created and expiry_date and batch.expiry_date is None:
            batch.expiry_date = expiry_date
        batch.quantity_on_hand += quantity
        batch.save()
    stock.quantity_on_hand += quantity
    stock.save()
    return StockTransactionLine.objects.create(
        transaction=txn, product=product, batch=batch, quantity=quantity,
        unit_cost=product.cost_price if unit_cost is None else unit_cost)


def _remove(txn, product, warehouse, quantity, *, batch=None, allow_expired=False, unit_cost=None):
    """Take `quantity` out. Batch products are consumed First-Expiry-First-Out."""
    if quantity <= 0:
        raise StockError('Quantity must be greater than zero.')
    stock = _locked_stock(product, warehouse)
    if quantity > stock.available:
        raise StockError(f'Insufficient stock for {product.sku} in {warehouse.name}: '
                         f'requested {quantity}, available {stock.available}.')
    cost = product.cost_price if unit_cost is None else unit_cost
    lines = []
    if product.tracks_batches:
        today = timezone.localdate()
        if batch is not None:
            batches = list(StockBatch.objects.select_for_update().filter(pk=batch.pk, warehouse=warehouse,
                                                                         product=product))
            if not batches:
                raise StockError(f'Batch not found for {product.sku} in {warehouse.name}.')
        else:
            batches = list(StockBatch.objects.select_for_update()
                           .filter(product=product, warehouse=warehouse, quantity_on_hand__gt=0)
                           .order_by(F('expiry_date').asc(nulls_last=True), 'received_at', 'batch_id'))
        usable = []
        for b in batches:
            if b.expiry_date and b.expiry_date < today and not allow_expired:
                if batch is not None:
                    raise StockError(f'Batch {b.batch_number} of {product.sku} expired on '
                                     f'{b.expiry_date:%d-%m-%Y}; it cannot be dispatched.')
                continue   # FR-16: expired batches are never auto-picked
            usable.append(b)
        if sum(b.quantity_on_hand for b in usable) < quantity:
            raise StockError(f'Insufficient non-expired stock for {product.sku} in {warehouse.name} '
                             f'(expired batches cannot be dispatched).')
        remaining = quantity
        for b in usable:
            take = min(b.quantity_on_hand, remaining)
            if take <= 0:
                continue
            b.quantity_on_hand -= take
            b.save()
            lines.append(StockTransactionLine.objects.create(
                transaction=txn, product=product, batch=b, quantity=-take, unit_cost=cost))
            remaining -= take
            if remaining == 0:
                break
    else:
        lines.append(StockTransactionLine.objects.create(
            transaction=txn, product=product, quantity=-quantity, unit_cost=cost))
    stock.quantity_on_hand -= quantity
    stock.save()
    return lines


def _after(products):
    for product in {p.pk: p for p in products}.values():
        check_reorder(product)


# ------------------------------------------------------------------ public API
@transaction.atomic
def record_in(*, warehouse, user, lines, transaction_type='IN', reference_type='MANUAL', reference_id=None,
              notes='', enforce_tracking=True):
    """FR-06 stock-in. lines: [{'product', 'quantity', 'batch_number', 'expiry_date', 'unit_cost'}]"""
    if not lines:
        raise StockError('Nothing to record.')
    txn = _new_transaction(transaction_type, warehouse, user, reference_type, reference_id, notes)
    for ln in lines:
        _add(txn, ln['product'], warehouse, ln['quantity'], batch_number=ln.get('batch_number'),
             expiry_date=ln.get('expiry_date'), unit_cost=ln.get('unit_cost'), enforce_tracking=enforce_tracking)
    audit.log(None, 'CREATE', 'stock_transaction', txn.pk, new=f'{transaction_type} {reference_type}', user=user)
    return txn


@transaction.atomic
def record_out(*, warehouse, user, lines, transaction_type='OUT', reference_type='MANUAL', reference_id=None,
               notes='', allow_expired=False):
    """FR-07 stock-out; refuses to dispatch more than is available.
    lines: [{'product', 'quantity', 'batch' (optional), 'unit_cost' (optional)}]"""
    if not lines:
        raise StockError('Nothing to record.')
    txn = _new_transaction(transaction_type, warehouse, user, reference_type, reference_id, notes)
    for ln in lines:
        _remove(txn, ln['product'], warehouse, ln['quantity'], batch=ln.get('batch'),
                allow_expired=allow_expired, unit_cost=ln.get('unit_cost'))
    _after(ln['product'] for ln in lines)
    audit.log(None, 'CREATE', 'stock_transaction', txn.pk, new=f'{transaction_type} {reference_type}', user=user)
    return txn


@transaction.atomic
def record_adjustment(*, warehouse, user, lines, reference_type='MANUAL', reference_id=None, notes='',
                      enforce_tracking=True):
    """Signed adjustment lines: positive adds, negative removes (expired stock may be written off)."""
    txn = _new_transaction('ADJUSTMENT', warehouse, user, reference_type, reference_id, notes)
    for ln in lines:
        qty = ln['quantity']
        if qty > 0:
            _add(txn, ln['product'], warehouse, qty, batch_number=ln.get('batch_number'),
                 expiry_date=ln.get('expiry_date'), enforce_tracking=enforce_tracking)
        elif qty < 0:
            _remove(txn, ln['product'], warehouse, -qty, allow_expired=True)
    _after(ln['product'] for ln in lines)
    audit.log(None, 'CREATE', 'stock_transaction', txn.pk, new='ADJUSTMENT', user=user)
    return txn


# ------------------------------------------------------------------ adjustments (FR-08)
@transaction.atomic
def request_adjustment(*, user, product, warehouse, quantity_change, reason, batch_number='', expiry_date=None,
                       request=None):
    """Mandatory reason; approvers apply it immediately, others only up to the threshold."""
    reason = (reason or '').strip()
    if not reason:
        raise StockError('A reason is required for every stock adjustment.')
    if quantity_change == 0:
        raise StockError('Quantity change cannot be zero.')
    adj = StockAdjustment.objects.create(
        product=product, warehouse=warehouse, quantity_change=quantity_change, reason=reason,
        batch_number=batch_number or '', expiry_date=expiry_date, requested_by=user)
    audit.log_obj(request, 'CREATE', adj, user=user)
    is_approver = user.can('stock.adjust.approve')
    if is_approver or abs(quantity_change) <= settings.ADJUSTMENT_APPROVAL_THRESHOLD:
        apply_adjustment(adj, approver=user if is_approver else None, request=request, auto=True)
        adj.refresh_from_db()
    else:
        notify_users(users_with_perm('stock.adjust.approve'), 'APPROVAL',
                     f'Approval needed: adjustment {quantity_change:+d} of {product.sku} in {warehouse.name} '
                     f'requested by {user.username}')
    return adj


@transaction.atomic
def apply_adjustment(adj, *, approver=None, request=None, auto=False):
    adj = StockAdjustment.objects.select_for_update().get(pk=adj.pk)
    if adj.status != 'Pending':
        raise StockError('This adjustment has already been processed.')
    record_adjustment(
        warehouse=adj.warehouse, user=approver or adj.requested_by, reference_id=adj.pk, notes=adj.reason,
        lines=[{'product': adj.product, 'quantity': adj.quantity_change, 'batch_number': adj.batch_number,
                'expiry_date': adj.expiry_date}])
    adj.status = 'Approved'
    adj.approved_by = approver
    adj.decided_at = timezone.now()
    adj.save()
    audit.log_obj(request, 'APPROVE', adj, user=approver or adj.requested_by)
    if not auto and adj.requested_by_id != getattr(approver, 'pk', None):
        notify_users([adj.requested_by], 'APPROVAL', f'Your adjustment #{adj.pk} for {adj.product.sku} was approved')
    return adj


@transaction.atomic
def reject_adjustment(adj, *, approver, request=None):
    adj = StockAdjustment.objects.select_for_update().get(pk=adj.pk)
    if adj.status != 'Pending':
        raise StockError('This adjustment has already been processed.')
    adj.status, adj.approved_by, adj.decided_at = 'Rejected', approver, timezone.now()
    adj.save()
    audit.log_obj(request, 'REJECT', adj, user=approver)
    notify_users([adj.requested_by], 'APPROVAL', f'Your adjustment #{adj.pk} for {adj.product.sku} was rejected')
    return adj


# ------------------------------------------------------------------ transfers (FR-09)
@transaction.atomic
def create_transfer(*, user, from_warehouse, to_warehouse, transfer_date, items, notes='', request=None):
    """items: [(product, quantity)]. Needs approval before stock moves."""
    if from_warehouse.pk == to_warehouse.pk:
        raise StockError('Source and destination warehouse must be different.')
    if not items:
        raise StockError('Add at least one product to transfer.')
    transfer = StockTransfer.objects.create(
        transfer_number=next_number(StockTransfer, 'transfer_number', 'TR'), from_warehouse=from_warehouse,
        to_warehouse=to_warehouse, created_by=user, transfer_date=transfer_date, notes=notes)
    for product, qty in items:
        if qty <= 0:
            raise StockError('Quantities must be greater than zero.')
        StockTransferItem.objects.create(transfer=transfer, product=product, quantity=qty)
    audit.log_obj(request, 'CREATE', transfer, user=user)
    notify_users(users_with_perm('stock.transfer.approve'), 'APPROVAL',
                 f'Approval needed: transfer {transfer.transfer_number} '
                 f'{from_warehouse.name} -> {to_warehouse.name}')
    return transfer


def _locked_transfer(transfer):
    return StockTransfer.objects.select_for_update().get(pk=transfer.pk)


@transaction.atomic
def approve_transfer(transfer, *, approver, request=None):
    transfer = _locked_transfer(transfer)
    if transfer.status != 'Pending':
        raise StockError('Only pending transfers can be approved.')
    transfer.status, transfer.approved_by = 'Approved', approver
    transfer.save()
    audit.log_obj(request, 'APPROVE', transfer, user=approver)
    notify_users([transfer.created_by], 'APPROVAL', f'Transfer {transfer.transfer_number} was approved')
    return transfer


@transaction.atomic
def reject_transfer(transfer, *, approver, request=None):
    transfer = _locked_transfer(transfer)
    if transfer.status not in ('Pending', 'Approved'):
        raise StockError('This transfer can no longer be cancelled.')
    transfer.status = 'Cancelled'
    transfer.save()
    audit.log_obj(request, 'REJECT', transfer, user=approver)
    notify_users([transfer.created_by], 'APPROVAL', f'Transfer {transfer.transfer_number} was cancelled')
    return transfer


@transaction.atomic
def ship_transfer(transfer, *, user, request=None):
    """Approved -> In Transit: stock leaves the source warehouse (TRANSFER_OUT)."""
    transfer = _locked_transfer(transfer)
    if transfer.status != 'Approved':
        raise StockError('Only approved transfers can be shipped.')
    items = list(transfer.items.select_related('product'))
    record_out(warehouse=transfer.from_warehouse, user=user, transaction_type='TRANSFER_OUT',
               reference_type='TRANSFER', reference_id=transfer.pk, notes=transfer.transfer_number,
               allow_expired=False, lines=[{'product': i.product, 'quantity': i.quantity} for i in items])
    transfer.status = 'In Transit'
    transfer.save()
    audit.log_obj(request, 'SHIP', transfer, user=user)
    return transfer


@transaction.atomic
def receive_transfer(transfer, *, user, request=None):
    """In Transit -> Completed: stock arrives (TRANSFER_IN) keeping batch and expiry."""
    transfer = _locked_transfer(transfer)
    if transfer.status != 'In Transit':
        raise StockError('Only transfers in transit can be received.')
    out_lines = list(StockTransactionLine.objects.filter(
        transaction__transaction_type='TRANSFER_OUT', transaction__reference_type='TRANSFER',
        transaction__reference_id=transfer.pk).select_related('product', 'batch'))
    txn = _new_transaction('TRANSFER_IN', transfer.to_warehouse, user, 'TRANSFER', transfer.pk,
                           transfer.transfer_number)
    for src in out_lines:
        _add_transferred(txn, src, transfer.to_warehouse)
    transfer.status = 'Completed'
    transfer.save()
    audit.log_obj(request, 'RECEIVE', transfer, user=user)
    notify_users([transfer.created_by], 'ORDER_STATUS', f'Transfer {transfer.transfer_number} completed')
    return transfer


def _add_transferred(txn, src_line, warehouse):
    """Like _add but keeps the original batch + expiry and accepts already-expired
    batches (the goods physically exist at the destination)."""
    product, quantity = src_line.product, -src_line.quantity
    stock = _locked_stock(product, warehouse)
    batch = None
    if src_line.batch is not None:
        batch, _ = StockBatch.objects.get_or_create(
            product=product, warehouse=warehouse, batch_number=src_line.batch.batch_number,
            defaults={'expiry_date': src_line.batch.expiry_date, 'quantity_on_hand': 0})
        batch = StockBatch.objects.select_for_update().get(pk=batch.pk)
        batch.quantity_on_hand += quantity
        batch.save()
    stock.quantity_on_hand += quantity
    stock.save()
    StockTransactionLine.objects.create(transaction=txn, product=product, batch=batch, quantity=quantity,
                                        unit_cost=src_line.unit_cost)


# ------------------------------------------------------------------ stock counting (FR-10)
@transaction.atomic
def create_count(*, user, warehouse, count_date, request=None):
    """Snapshot the system quantity of every product held in the warehouse."""
    count = StockCount.objects.create(
        count_number=next_number(StockCount, 'count_number', 'CNT'), warehouse=warehouse,
        performed_by=user, count_date=count_date)
    for stock in Stock.objects.filter(warehouse=warehouse).select_related('product'):
        StockCountItem.objects.create(count=count, product=stock.product, system_quantity=stock.quantity_on_hand)
    audit.log_obj(request, 'CREATE', count, user=user)
    return count


@transaction.atomic
def save_count_quantities(count, quantities):
    """quantities: {product_id: counted_quantity or None}"""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != 'Open':
        raise StockError('Only open counts can be edited.')
    for item in count.items.all():
        if item.product_id in quantities:
            qty = quantities[item.product_id]
            item.counted_quantity = qty
            item.variance = 0 if qty is None else qty - item.system_quantity
            item.save()
    return count


@transaction.atomic
def complete_count(count, *, user, request=None):
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != 'Open':
        raise StockError('Only open counts can be completed.')
    missing = count.items.filter(counted_quantity__isnull=True).count()
    if missing:
        raise StockError(f'{missing} product(s) have not been counted yet.')
    count.status = 'Completed'
    count.save()
    audit.log_obj(request, 'UPDATE', count, user=user)
    if count.items.exclude(variance=0).exists():
        notify_users(users_with_perm('stock.adjust.approve'), 'APPROVAL',
                     f'Approval needed: stock count {count.count_number} has variances')
    return count


@transaction.atomic
def approve_count(count, *, approver, request=None):
    """Approving posts the variances to the ledger as ADJUSTMENT transactions."""
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != 'Completed':
        raise StockError('Only completed counts can be approved.')
    lines = [{'product': i.product, 'quantity': i.variance, 'batch_number': f'COUNT-{count.count_number}'}
             for i in count.items.select_related('product').exclude(variance=0)]
    if lines:
        record_adjustment(warehouse=count.warehouse, user=approver, lines=lines, reference_type='COUNT',
                          reference_id=count.pk, notes=f'Variance from {count.count_number}',
                          enforce_tracking=False)
    count.status = 'Approved'
    count.save()
    audit.log_obj(request, 'APPROVE', count, user=approver)
    return count


# ------------------------------------------------------------------ queries
def low_stock_products():
    """FR-17: products whose total quantity on hand <= reorder level (level 0 = disabled)."""
    from app_product.models import Product
    return list(Product.objects.filter(status='Active', reorder_level__gt=0)
                .annotate(total=Coalesce(Sum('stocks__quantity_on_hand'), 0))
                .filter(total__lte=F('reorder_level')).order_by('total', 'name'))
