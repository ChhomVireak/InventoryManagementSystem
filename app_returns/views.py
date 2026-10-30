from datetime import datetime

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from app_accounts.decorators import perm_required
from app_backend import crud
from app_returns import services
from app_returns.models import Return
from app_stock.forms import active_warehouses
from app_stock.models import StockTransaction
from app_stock.services import StockError

VIEW = ('return.process', 'report.view')


@perm_required(*VIEW)
def index(request):
    ctx = crud.list_context(
        request, Return.objects.select_related('created_by'),
        search_fields=['return_number', 'reason'],
        sort_fields={'number': 'return_number', 'date': 'return_date', 'status': 'status', 'type': 'return_type'},
        default_sort='-return_id', filters={'status': 'status', 'type': 'return_type'})
    ctx.update(statuses=[s for s, _ in Return.STATUS], types=Return.TYPES)
    return render(request, 'pages/returns/index.html', ctx)


@perm_required(*VIEW)
def detail(request, id):
    ret = get_object_or_404(Return.objects.select_related('created_by'), pk=id)
    return render(request, 'pages/returns/detail.html', {
        'ret': ret, 'items': ret.items.select_related('product'), 'warehouses': active_warehouses(),
        'ledger': StockTransaction.objects.filter(reference_type='RETURN', reference_id=id)})


@perm_required('return.process')
def new(request):
    """Step 1: choose type + original order number. Step 2: pick quantities / condition / reason."""
    return_type = request.GET.get('type') or request.POST.get('return_type') or ''
    number = request.GET.get('order') or request.POST.get('order_number') or ''
    ctx = {'return_type': return_type, 'order_number': number, 'types': Return.TYPES,
           'today': timezone.localdate(), 'rows': None, 'order': None}
    if return_type not in dict(Return.TYPES):
        ctx['return_type'] = ''
        return render(request, 'pages/returns/form.html', ctx)
    order = services.find_order(return_type, number)
    if order is None:
        if number:
            messages.error(request, f'Order "{number}" was not found - a return must reference an existing order.')
        return render(request, 'pages/returns/form.html', ctx)
    if order.status in ('Draft', 'Cancelled'):
        messages.error(request, 'Only orders with received / shipped goods can be returned.')
        return render(request, 'pages/returns/form.html', ctx)
    rows = services.returnable_items(return_type, order)
    ctx.update(order=order, rows=rows)
    if request.method == 'POST' and request.POST.get('step') == 'save':
        entries = []
        try:
            for item, _used, _left in rows:
                raw = request.POST.get(f'qty_{item.pk}', '').strip() or '0'
                if not raw.isdigit():
                    raise StockError(f'{item.product.sku}: quantity must be a whole number.')
                condition = request.POST.get(f'cond_{item.pk}', 'Restockable')
                if condition not in ('Restockable', 'Damaged'):
                    condition = 'Restockable'
                entries.append((item, int(raw), condition))
            try:
                return_date = datetime.fromisoformat(request.POST.get('return_date')).date()
            except (TypeError, ValueError):
                raise StockError('Enter a valid return date.')
            ret = services.create_return(user=request.user, return_type=return_type, order=order,
                                         return_date=return_date, reason=request.POST.get('reason'),
                                         entries=entries, request=request)
        except StockError as exc:
            messages.error(request, str(exc))
            ctx['posted'] = request.POST
        else:
            messages.success(request, f'Return {ret.return_number} created - waiting for approval.')
            return redirect(f'/returns/{ret.pk}/')
    return render(request, 'pages/returns/form.html', ctx)


@perm_required('return.process', 'stock.adjust.approve')
@require_POST
def action(request, id, name):
    ret = get_object_or_404(Return, pk=id)
    try:
        if name == 'approve':
            if not request.user.can('stock.adjust.approve'):
                raise PermissionError
            services.approve_return(ret, approver=request.user, request=request)
        elif name == 'cancel':
            services.cancel_return(ret, user=request.user, request=request)
        elif name == 'complete':
            if not request.user.can('return.process'):
                raise PermissionError
            warehouse = active_warehouses().filter(pk=request.POST.get('warehouse') or 0).first()
            if warehouse is None:
                raise StockError('Choose the warehouse.')
            services.complete_return(ret, warehouse=warehouse, user=request.user, request=request)
        else:
            raise Http404
        messages.success(request, f'Return {ret.return_number}: {name} done.')
    except PermissionError:
        messages.error(request, 'You do not have permission for this action.')
    except StockError as exc:
        messages.error(request, str(exc))
    return redirect(f'/returns/{id}/')
