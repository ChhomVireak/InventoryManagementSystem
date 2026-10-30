from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from app_accounts.decorators import perm_required
from app_backend import crud
from app_warehouse.forms import WarehouseForm
from app_warehouse.models import Warehouse

BASE = '/warehouse/'


def index(request):
    qs = Warehouse.objects.annotate(item_count=Count('stocks'))
    ctx = crud.list_context(request, qs, search_fields=['name', 'location', 'address'],
                            sort_fields={'name': 'name', 'location': 'location', 'status': 'status'},
                            default_sort='name', filters={'status': 'status'})
    return render(request, 'pages/warehouse/index.html', ctx)


@perm_required('warehouse.manage')
def show_warehouse(request):
    return crud.show_form(request, WarehouseForm, 'Warehouse', BASE)


@perm_required('warehouse.manage')
def create_warehouse(request):
    return crud.save_form(request, WarehouseForm, 'Warehouse', BASE)


@perm_required('warehouse.manage')
def edit_warehouse(request, id):
    return crud.show_form(request, WarehouseForm, 'Warehouse', BASE, get_object_or_404(Warehouse, pk=id))


@perm_required('warehouse.manage')
def update_warehouse(request, id):
    return crud.save_form(request, WarehouseForm, 'Warehouse', BASE, get_object_or_404(Warehouse, pk=id))


@perm_required('warehouse.manage')
def delete_warehouse(request, id):
    return crud.delete_object(request, Warehouse, id, 'Warehouse', BASE, 'Set it to Inactive instead.')
