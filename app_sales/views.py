from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app_accounts.decorators import perm_required
from app_backend import crud
from app_backend.lines import parse_lines
from app_customer.models import Customer
from app_sales import services
from app_sales.forms import SalesOrderForm
from app_sales.models import SalesOrder
from app_stock.forms import active_warehouses
from app_stock.models import StockTransaction
from app_stock.services import StockError

VIEW = ('so.create', 'so.dispatch', 'report.view')


@perm_required(*VIEW)
def index(request):
    ctx = crud.list_context(
        request, SalesOrder.objects.select_related('customer', 'created_by'),
        search_fields=['so_number', 'customer__name', 'notes'],
        sort_fields={'number': 'so_number', 'customer': 'customer__name', 'date': 'order_date',
                     'status': 'status', 'total': 'total_amount'},
        default_sort='-so_id', filters={'status': 'status', 'customer': 'customer_id'})
    ctx.update(statuses=[s for s, _ in SalesOrder.STATUS], customers=Customer.objects.all())
    return render(request, 'pages/sales/index.html', ctx)


@perm_required(*VIEW)
def detail(request, id):
    so = get_object_or_404(SalesOrder.objects.select_related('customer', 'created_by'), pk=id)
    return render(request, 'pages/sales/detail.html', {
        'so': so, 'items': so.items.select_related('product'),
        'dispatches': StockTransaction.objects.filter(reference_type='SO', reference_id=id)})


def _form_page(request, form, rows, errors, title, action, so=None):
    return render(request, 'pages/sales/form.html', {
        'form': form, 'rows': rows, 'line_errors': errors, 'title': title, 'action': action, 'so': so,
        'back_url': f'/sales/{so.pk}/' if so else '/sales/'})


@perm_required('so.create')
def show_sales(request):
    return _form_page(request, SalesOrderForm(initial={'order_date': timezone.localdate()}), [], [],
                      'New Sales Order', '/sales/create')


@perm_required('so.create')
def create_sales(request):
    if request.method != 'POST':
        return redirect('/sales/')
    form = SalesOrderForm(request.POST)
    rows, errors = parse_lines(request.POST)
    if form.is_valid() and not errors:
        so = services.save_order(form=form, rows=rows, user=request.user, request=request)
        messages.success(request, f'Sales order {so.so_number} created')
        return redirect(f'/sales/{so.pk}/')
    return _form_page(request, form, rows, errors, 'New Sales Order', '/sales/create')


@perm_required('so.create')
def edit_sales(request, id):
    so = get_object_or_404(SalesOrder, pk=id)
    if not so.can_edit:
        messages.error(request, 'Only draft sales orders can be edited.')
        return redirect(f'/sales/{id}/')
    rows = [{'product': i.product, 'quantity': i.quantity_ordered, 'price': i.unit_price}
            for i in so.items.select_related('product')]
    return _form_page(request, SalesOrderForm(instance=so), rows, [], f'Edit {so.so_number}',
                      f'/sales/update/{id}', so)


@perm_required('so.create')
def update_sales(request, id):
    so = get_object_or_404(SalesOrder, pk=id)
    if request.method != 'POST' or not so.can_edit:
        messages.error(request, 'Only draft sales orders can be edited.')
        return redirect(f'/sales/{id}/')
    form = SalesOrderForm(request.POST, instance=so)
    rows, errors = parse_lines(request.POST)
    if form.is_valid() and not errors:
        services.save_order(form=form, rows=rows, user=request.user, request=request, order=so)
        messages.success(request, f'Sales order {so.so_number} updated')
        return redirect(f'/sales/{id}/')
    return _form_page(request, form, rows, errors, f'Edit {so.so_number}', f'/sales/update/{id}', so)


@perm_required('so.create')
@require_POST
def delete_sales(request, id):
    so = get_object_or_404(SalesOrder, pk=id)
    if so.status != 'Draft':
        messages.error(request, 'Only draft sales orders can be deleted - cancel it instead.')
        return redirect(f'/sales/{id}/')
    return crud.delete_object(request, SalesOrder, id, 'Sales order', '/sales/')


@perm_required('so.create', 'so.dispatch')
@require_POST
def action(request, id, name):
    so = get_object_or_404(SalesOrder, pk=id)
    try:
        if name == 'confirm':
            if not request.user.can('so.create'):
                raise PermissionError
            services.set_status(so, 'Confirmed', user=request.user, request=request, allowed_from=['Draft'])
            messages.success(request, f'{so.so_number} confirmed.')
        elif name == 'cancel':
            if not request.user.can('so.create'):
                raise PermissionError
            services.set_status(so, 'Cancelled', user=request.user, request=request,
                                allowed_from=['Draft', 'Confirmed'])
            messages.success(request, f'{so.so_number} cancelled.')
        elif name == 'deliver':
            if not request.user.can('so.dispatch'):
                raise PermissionError
            services.set_status(so, 'Delivered', user=request.user, request=request, allowed_from=['Shipped'])
            messages.success(request, f'{so.so_number} marked as delivered.')
        else:
            raise Http404
    except PermissionError:
        messages.error(request, 'You do not have permission for this action.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect(f'/sales/{id}/')


@perm_required('so.dispatch')
def dispatch(request, id):
    so = get_object_or_404(SalesOrder.objects.select_related('customer'), pk=id)
    items = list(so.items.select_related('product'))
    error = ''
    if so.status != 'Confirmed':
        messages.error(request, 'Only confirmed orders can be dispatched.')
        return redirect(f'/sales/{id}/')
    if request.method == 'POST':
        warehouse = active_warehouses().filter(pk=request.POST.get('warehouse') or 0).first()
        try:
            if warehouse is None:
                raise StockError('Choose the warehouse to dispatch from.')
            quantities = {}
            for item in items:
                raw = request.POST.get(f'qty_{item.pk}', '').strip() or '0'
                if not raw.isdigit():
                    raise StockError(f'{item.product.sku}: quantity must be a whole number.')
                quantities[item.pk] = int(raw)
            services.dispatch(so, warehouse=warehouse, user=request.user, quantities=quantities, request=request)
        except StockError as exc:
            error = str(exc)
        else:
            messages.success(request, f'Goods dispatched for {so.so_number}.')
            return redirect(f'/sales/{id}/')
    return render(request, 'pages/sales/dispatch.html', {
        'so': so, 'items': items, 'warehouses': active_warehouses(), 'error': error, 'posted': request.POST})
