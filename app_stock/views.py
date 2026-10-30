from datetime import timedelta

from django.contrib import messages
from django.http import Http404
from django.db.models import F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app_accounts.decorators import perm_required
from app_backend import crud
from app_backend.lines import parse_lines
from app_product.models import Category, Product
from app_stock import services
from app_stock.forms import AdjustmentForm, CountForm, StockInForm, StockOutForm, TransferForm
from app_stock.models import (Stock, StockAdjustment, StockBatch, StockCount, StockTransaction, StockTransfer)
from app_stock.services import StockError
from app_warehouse.models import Warehouse

VIEW_LEDGER = ('stock.in', 'stock.out', 'stock.adjust.request', 'stock.adjust.approve', 'stock.transfer.request',
               'stock.transfer.approve', 'stock.count', 'report.view')


# ---------------------------------------------------------------- stock levels
def index(request):
    qs = Stock.objects.select_related('product', 'warehouse', 'product__category')
    if request.GET.get('low') == '1':
        qs = qs.filter(product__reorder_level__gt=0, quantity_on_hand__lte=F('product__reorder_level'))
    ctx = crud.list_context(
        request, qs, search_fields=['product__sku', 'product__name', 'product__barcode', 'warehouse__name'],
        sort_fields={'sku': 'product__sku', 'product': 'product__name', 'warehouse': 'warehouse__name',
                     'qty': 'quantity_on_hand', 'updated': 'last_updated'},
        default_sort='product__name', filters={'warehouse': 'warehouse_id', 'category': 'product__category_id'})
    ctx.update(warehouses=Warehouse.objects.all(), categories=Category.objects.all(),
               low=request.GET.get('low', ''))
    return render(request, 'pages/stock/index.html', ctx)


# ---------------------------------------------------------------- stock in / out (FR-06, FR-07, FR-25)
@perm_required('stock.in')
def stock_in(request):
    form = StockInForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            txn = services.record_in(
                warehouse=d['warehouse'], user=request.user, notes=d['reference'],
                lines=[{'product': d['product'], 'quantity': d['quantity'], 'batch_number': d['batch_number'],
                        'expiry_date': d['expiry_date'], 'unit_cost': d['unit_cost']}])
        except StockError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f'Stock-in recorded (transaction #{txn.pk})')
            return redirect('/stock/in/')
    return render(request, 'pages/stock/movement.html', {
        'form': form, 'title': 'Stock In (Goods Receipt)', 'action': '/stock/in/', 'kind': 'in'})


@perm_required('stock.out')
def stock_out(request):
    form = StockOutForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            txn = services.record_out(
                warehouse=d['warehouse'], user=request.user, notes=d['reference'],
                lines=[{'product': d['product'], 'quantity': d['quantity']}])
        except StockError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, f'Stock-out recorded (transaction #{txn.pk})')
            return redirect('/stock/out/')
    return render(request, 'pages/stock/movement.html', {
        'form': form, 'title': 'Stock Out (Issue / Dispatch)', 'action': '/stock/out/', 'kind': 'out'})


# ---------------------------------------------------------------- ledger + batches
@perm_required(*VIEW_LEDGER)
def transactions(request):
    qs = StockTransaction.objects.select_related('warehouse', 'user').prefetch_related('lines__product')
    date_from, date_to = request.GET.get('from', ''), request.GET.get('to', '')
    if date_from:
        qs = qs.filter(transaction_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction_date__date__lte=date_to)
    ctx = crud.list_context(
        request, qs, search_fields=['notes', 'lines__product__sku', 'lines__product__name', 'user__username'],
        sort_fields={'date': 'transaction_date', 'type': 'transaction_type', 'warehouse': 'warehouse__name',
                     'user': 'user__username'},
        default_sort='-transaction_date', filters={'type': 'transaction_type', 'warehouse': 'warehouse_id'})
    ctx.update(types=StockTransaction.TYPES, warehouses=Warehouse.objects.all(), date_from=date_from,
               date_to=date_to)
    return render(request, 'pages/stock/transactions.html', ctx)


@perm_required(*VIEW_LEDGER)
def transaction_detail(request, id):
    txn = get_object_or_404(StockTransaction.objects.select_related('warehouse', 'user'), pk=id)
    return render(request, 'pages/stock/transaction_detail.html', {
        'txn': txn, 'lines': txn.lines.select_related('product', 'batch')})


def batches(request):
    today = timezone.localdate()
    qs = StockBatch.objects.select_related('product', 'warehouse').filter(quantity_on_hand__gt=0)
    state = request.GET.get('state', '')
    if state == 'expired':
        qs = qs.filter(expiry_date__lt=today)
    elif state == 'soon':
        qs = qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
    ctx = crud.list_context(
        request, qs, search_fields=['batch_number', 'product__sku', 'product__name'],
        sort_fields={'product': 'product__name', 'batch': 'batch_number', 'expiry': 'expiry_date',
                     'qty': 'quantity_on_hand', 'warehouse': 'warehouse__name'},
        default_sort='expiry_date', filters={'warehouse': 'warehouse_id'})
    ctx.update(warehouses=Warehouse.objects.all(), state=state, today=today)
    return render(request, 'pages/stock/batches.html', ctx)


# ---------------------------------------------------------------- adjustments (FR-08)
@perm_required('stock.adjust.request', 'stock.adjust.approve')
def adjustment_index(request):
    ctx = crud.list_context(
        request, StockAdjustment.objects.select_related('product', 'warehouse', 'requested_by', 'approved_by'),
        search_fields=['product__sku', 'product__name', 'reason'],
        sort_fields={'date': 'created_at', 'status': 'status', 'qty': 'quantity_change'},
        default_sort='-created_at', filters={'status': 'status'})
    return render(request, 'pages/stock/adjustments.html', ctx)


@perm_required('stock.adjust.request', 'stock.adjust.approve')
def adjustment_new(request):
    form = AdjustmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            adj = services.request_adjustment(
                user=request.user, product=d['product'], warehouse=d['warehouse'], reason=d['reason'],
                quantity_change=d['quantity_change'], batch_number=d['batch_number'],
                expiry_date=d['expiry_date'], request=request)
        except StockError as exc:
            form.add_error(None, str(exc))
        else:
            if adj.status == 'Approved':
                messages.success(request, 'Adjustment applied.')
            else:
                messages.success(request, 'Adjustment submitted for approval (above the approval threshold).')
            return redirect('/stock/adjustments/')
    return render(request, 'pages/stock/adjustment_form.html', {'form': form})


@perm_required('stock.adjust.approve')
@require_POST
def adjustment_decide(request, id, decision):
    if decision not in ('approve', 'reject'):
        raise Http404
    adj = get_object_or_404(StockAdjustment, pk=id)
    try:
        if decision == 'approve':
            services.apply_adjustment(adj, approver=request.user, request=request)
            messages.success(request, f'Adjustment #{id} approved and applied.')
        else:
            services.reject_adjustment(adj, approver=request.user, request=request)
            messages.success(request, f'Adjustment #{id} rejected.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect('/stock/adjustments/')


# ---------------------------------------------------------------- transfers (FR-09)
TRANSFER_PERMS = ('stock.transfer.request', 'stock.transfer.approve')


@perm_required(*TRANSFER_PERMS)
def transfer_index(request):
    ctx = crud.list_context(
        request, StockTransfer.objects.select_related('from_warehouse', 'to_warehouse', 'created_by'),
        search_fields=['transfer_number', 'from_warehouse__name', 'to_warehouse__name'],
        sort_fields={'number': 'transfer_number', 'date': 'transfer_date', 'status': 'status'},
        default_sort='-transfer_id', filters={'status': 'status'})
    ctx['statuses'] = [s for s, _ in StockTransfer.STATUS]
    return render(request, 'pages/stock/transfers.html', ctx)


@perm_required(*TRANSFER_PERMS)
def transfer_new(request):
    form = TransferForm(request.POST or None, initial={'transfer_date': timezone.localdate()})
    rows, errors = [], []
    if request.method == 'POST':
        rows, errors = parse_lines(request.POST, with_price=False)
        if form.is_valid() and not errors:
            d = form.cleaned_data
            try:
                transfer = services.create_transfer(
                    user=request.user, from_warehouse=d['from_warehouse'], to_warehouse=d['to_warehouse'],
                    transfer_date=d['transfer_date'], notes=d['notes'], request=request,
                    items=[(r['product'], r['quantity']) for r in rows])
            except StockError as exc:
                errors.append(str(exc))
            else:
                messages.success(request, f'Transfer {transfer.transfer_number} created - waiting for approval.')
                return redirect(f'/stock/transfers/{transfer.pk}/')
    return render(request, 'pages/stock/transfer_form.html', {'form': form, 'rows': rows, 'line_errors': errors})


@perm_required(*TRANSFER_PERMS)
def transfer_detail(request, id):
    transfer = get_object_or_404(StockTransfer.objects.select_related(
        'from_warehouse', 'to_warehouse', 'created_by', 'approved_by'), pk=id)
    ledger = StockTransaction.objects.filter(reference_type='TRANSFER', reference_id=id)
    return render(request, 'pages/stock/transfer_detail.html', {
        'transfer': transfer, 'items': transfer.items.select_related('product'), 'ledger': ledger})


@perm_required(*TRANSFER_PERMS)
@require_POST
def transfer_action(request, id, action):
    transfer = get_object_or_404(StockTransfer, pk=id)
    user = request.user
    try:
        if action in ('approve', 'reject'):
            if not user.can('stock.transfer.approve'):
                raise PermissionError
            if action == 'approve':
                services.approve_transfer(transfer, approver=user, request=request)
            else:
                services.reject_transfer(transfer, approver=user, request=request)
        elif action == 'cancel':
            services.reject_transfer(transfer, approver=user, request=request)
        elif action == 'ship':
            services.ship_transfer(transfer, user=user, request=request)
        elif action == 'receive':
            services.receive_transfer(transfer, user=user, request=request)
        else:
            raise StockError('Unknown action.')
        messages.success(request, f'Transfer {transfer.transfer_number}: {action} done.')
    except PermissionError:
        messages.error(request, 'Only an approver can approve or reject transfers.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect(f'/stock/transfers/{id}/')


# ---------------------------------------------------------------- stock counting (FR-10)
@perm_required('stock.count')
def count_index(request):
    ctx = crud.list_context(
        request, StockCount.objects.select_related('warehouse', 'performed_by'),
        search_fields=['count_number', 'warehouse__name'],
        sort_fields={'number': 'count_number', 'date': 'count_date', 'status': 'status'},
        default_sort='-count_id', filters={'status': 'status'})
    return render(request, 'pages/stock/counts.html', ctx)


@perm_required('stock.count')
def count_new(request):
    form = CountForm(request.POST or None, initial={'count_date': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        count = services.create_count(user=request.user, warehouse=form.cleaned_data['warehouse'],
                                      count_date=form.cleaned_data['count_date'], request=request)
        messages.success(request, f'Count {count.count_number} started with {count.items.count()} product(s).')
        return redirect(f'/stock/counts/{count.pk}/')
    return render(request, 'pages/stock/count_form.html', {'form': form})


@perm_required('stock.count')
def count_detail(request, id):
    count = get_object_or_404(StockCount.objects.select_related('warehouse', 'performed_by'), pk=id)
    items = count.items.select_related('product').order_by('product__name')
    totals = items.aggregate(sys=Sum('system_quantity'), counted=Sum('counted_quantity'), var=Sum('variance'))
    return render(request, 'pages/stock/count_detail.html', {
        'count': count, 'items': items, 'totals': totals,
        'variance_items': items.exclude(variance=0).count(),
    })


@perm_required('stock.count')
@require_POST
def count_action(request, id, action):
    count = get_object_or_404(StockCount, pk=id)
    try:
        if action in ('save', 'complete'):
            quantities = {}
            for item in count.items.all():
                raw = request.POST.get(f'counted_{item.product_id}', '').strip()
                if raw == '':
                    quantities[item.product_id] = None
                elif raw.isdigit():
                    quantities[item.product_id] = int(raw)
                else:
                    raise StockError(f'Counted quantity for {item.product.sku} must be a whole number >= 0.')
            services.save_count_quantities(count, quantities)
            if action == 'complete':
                services.complete_count(count, user=request.user, request=request)
                messages.success(request, 'Count completed - variance report is ready.')
            else:
                messages.success(request, 'Counted quantities saved.')
        elif action == 'add':
            product = Product.objects.filter(pk=request.POST.get('product') or 0).first()
            if product is None:
                raise StockError('Choose a product to add.')
            if count.status != 'Open':
                raise StockError('Only open counts can be edited.')
            from app_stock.models import StockCountItem
            StockCountItem.objects.get_or_create(count=count, product=product, defaults={'system_quantity': 0})
            messages.success(request, f'{product.sku} added to the count.')
        elif action == 'approve':
            if not request.user.can('stock.adjust.approve'):
                raise PermissionError
            services.approve_count(count, approver=request.user, request=request)
            messages.success(request, 'Count approved - variances posted to stock.')
        else:
            raise StockError('Unknown action.')
    except PermissionError:
        messages.error(request, 'Only an approver can approve a count.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect(f'/stock/counts/{id}/')
