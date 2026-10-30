from django.shortcuts import get_object_or_404, render

from app_accounts.decorators import perm_required
from app_backend import crud
from app_supplier.forms import SupplierForm
from app_supplier.models import Supplier

BASE = '/supplier/'


def index(request):
    ctx = crud.list_context(
        request, Supplier.objects.all(),
        search_fields=['name', 'email', 'phone', 'address', 'contact_person'],
        sort_fields={'name': 'name', 'email': 'email', 'phone': 'phone', 'status': 'status'},
        default_sort='name', filters={'status': 'status'})
    return render(request, 'pages/supplier/index.html', ctx)


@perm_required('partner.manage')
def show_supplier(request):
    return crud.show_form(request, SupplierForm, 'Supplier', BASE)


@perm_required('partner.manage')
def create_supplier(request):
    return crud.save_form(request, SupplierForm, 'Supplier', BASE)


@perm_required('partner.manage')
def edit_supplier(request, id):
    return crud.show_form(request, SupplierForm, 'Supplier', BASE, get_object_or_404(Supplier, pk=id))


@perm_required('partner.manage')
def update_supplier(request, id):
    return crud.save_form(request, SupplierForm, 'Supplier', BASE, get_object_or_404(Supplier, pk=id))


@perm_required('partner.manage')
def delete_supplier(request, id):
    return crud.delete_object(request, Supplier, id, 'Supplier', BASE, 'It is linked to orders - set it to Inactive instead.')
