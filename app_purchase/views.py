from datetime import date

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.http import Http404

from app_accounts import audit
from app_accounts.decorators import perm_required
from app_backend import crud
from app_backend.lines import parse_lines
from app_purchase import services
from app_purchase.forms import PurchaseOrderForm
from app_purchase.models import PurchaseOrder
from app_stock.forms import active_warehouses
from app_stock.models import StockTransaction
from app_stock.services import StockError
from app_supplier.models import Supplier

VIEW = ('po.create', 'po.approve', 'po.receive', 'report.view')


@perm_required(*VIEW)
def index(request):
    ctx = crud.list_context(
        request, PurchaseOrder.objects.select_related('supplier', 'created_by'),
        search_fields=['po_number', 'supplier__name', 'notes'],
        sort_fields={'number': 'po_number', 'supplier': 'supplier__name', 'date': 'order_date',
                     'status': 'status', 'total': 'total_amount'},
        default_sort='-po_id', filters={'status': 'status', 'supplier': 'supplier_id'})
    ctx.update(statuses=[s for s, _ in PurchaseOrder.STATUS], suppliers=Supplier.objects.all())
    return render(request, 'pages/purchase/index.html', ctx)


@perm_required(*VIEW)
def detail(request, id):
    po = get_object_or_404(PurchaseOrder.objects.select_related('supplier', 'created_by'), pk=id)
    return render(request, 'pages/purchase/detail.html', {
        'po': po, 'items': po.items.select_related('product'),
        'receipts': StockTransaction.objects.filter(reference_type='PO', reference_id=id)})


def _form_page(request, form, rows, errors, title, action, po=None):
    return render(request, 'pages/purchase/form.html', {
        'form': form, 'rows': rows, 'line_errors': errors, 'title': title, 'action': action, 'po': po,
        'back_url': f'/purchase/{po.pk}/' if po else '/purchase/'})


@perm_required('po.create')
def show_purchase(request):
    form = PurchaseOrderForm(initial={'order_date': timezone.localdate()})
    return _form_page(request, form, [], [], 'New Purchase Order', '/purchase/create')


@perm_required('po.create')
def create_purchase(request):
    if request.method != 'POST':
        return redirect('/purchase/')
    form = PurchaseOrderForm(request.POST)
    rows, errors = parse_lines(request.POST)
    if form.is_valid() and not errors:
        po = services.save_order(form=form, rows=rows, user=request.user, request=request)
        messages.success(request, f'Purchase order {po.po_number} created')
        return redirect(f'/purchase/{po.pk}/')
    return _form_page(request, form, rows, errors, 'New Purchase Order', '/purchase/create')


@perm_required('po.create')
def edit_purchase(request, id):
    po = get_object_or_404(PurchaseOrder, pk=id)
    if not po.can_edit:
        messages.error(request, 'Only draft purchase orders can be edited.')
        return redirect(f'/purchase/{id}/')
    rows = [{'product': i.product, 'quantity': i.quantity_ordered, 'price': i.unit_price}
            for i in po.items.select_related('product')]
    return _form_page(request, PurchaseOrderForm(instance=po), rows, [], f'Edit {po.po_number}',
                      f'/purchase/update/{id}', po)


@perm_required('po.create')
def update_purchase(request, id):
    po = get_object_or_404(PurchaseOrder, pk=id)
    if request.method != 'POST' or not po.can_edit:
        messages.error(request, 'Only draft purchase orders can be edited.')
        return redirect(f'/purchase/{id}/')
    form = PurchaseOrderForm(request.POST, instance=po)
    rows, errors = parse_lines(request.POST)
    if form.is_valid() and not errors:
        services.save_order(form=form, rows=rows, user=request.user, request=request, order=po)
        messages.success(request, f'Purchase order {po.po_number} updated')
        return redirect(f'/purchase/{id}/')
    return _form_page(request, form, rows, errors, f'Edit {po.po_number}', f'/purchase/update/{id}', po)


@perm_required('po.create')
@require_POST
def delete_purchase(request, id):
    po = get_object_or_404(PurchaseOrder, pk=id)
    if po.status != 'Draft':
        messages.error(request, 'Only draft purchase orders can be deleted - cancel it instead.')
        return redirect(f'/purchase/{id}/')
    return crud.delete_object(request, PurchaseOrder, id, 'Purchase order', '/purchase/')


@perm_required('po.create', 'po.approve')
@require_POST
def action(request, id, name):
    po = get_object_or_404(PurchaseOrder, pk=id)
    try:
        if name == 'approve':
            if not request.user.can('po.approve'):
                raise PermissionError
            services.set_status(po, 'Sent', user=request.user, request=request, allowed_from=['Draft'])
            messages.success(request, f'{po.po_number} approved and sent to the supplier.')
        elif name == 'cancel':
            services.set_status(po, 'Cancelled', user=request.user, request=request,
                                allowed_from=['Draft', 'Sent'])
            messages.success(request, f'{po.po_number} cancelled.')
        else:
            raise Http404
    except PermissionError:
        messages.error(request, 'Only a purchase approver can approve purchase orders.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect(f'/purchase/{id}/')


@perm_required('po.receive')
def receive(request, id):
    """FR-12: goods receiving against a PO (batch + expiry captured for tracked products)."""
    po = get_object_or_404(PurchaseOrder.objects.select_related('supplier'), pk=id)
    items = list(po.items.select_related('product'))
    error = ''
    if po.status not in ('Sent', 'Partial'):
        messages.error(request, 'This order is not open for receiving (it must be approved first).')
        return redirect(f'/purchase/{id}/')
    if request.method == 'POST':
        warehouse = active_warehouses().filter(pk=request.POST.get('warehouse') or 0).first()
        receipts = {}
        try:
            if warehouse is None:
                raise StockError('Choose the receiving warehouse.')
            for item in items:
                raw = request.POST.get(f'qty_{item.pk}', '').strip() or '0'
                if not raw.isdigit():
                    raise StockError(f'{item.product.sku}: quantity must be a whole number.')
                expiry = request.POST.get(f'expiry_{item.pk}') or None
                try:
                    expiry = date.fromisoformat(expiry) if expiry else None
                except ValueError:
                    raise StockError(f'{item.product.sku}: invalid expiry date.')
                receipts[item.pk] = {'qty': int(raw), 'batch_number': request.POST.get(f'batch_{item.pk}', '').strip(),
                                     'expiry_date': expiry}
            services.receive_goods(po, warehouse=warehouse, user=request.user, receipts=receipts, request=request)
        except StockError as exc:
            error = str(exc)
        else:
            messages.success(request, f'Goods received for {po.po_number}.')
            return redirect(f'/purchase/{id}/')
    return render(request, 'pages/purchase/receive.html', {
        'po': po, 'items': items, 'warehouses': active_warehouses(), 'error': error, 'posted': request.POST})
