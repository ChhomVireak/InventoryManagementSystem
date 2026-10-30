from django.shortcuts import get_object_or_404, render

from app_accounts.decorators import perm_required
from app_backend import crud
from app_customer.forms import CustomerForm
from app_customer.models import Customer

BASE = '/customer/'


def index(request):
    ctx = crud.list_context(
        request, Customer.objects.all(),
        search_fields=['name', 'email', 'phone', 'address'],
        sort_fields={'name': 'name', 'email': 'email', 'phone': 'phone', 'status': 'status'},
        default_sort='name', filters={'status': 'status'})
    return render(request, 'pages/customer/index.html', ctx)


@perm_required('partner.manage')
def show_customer(request):
    return crud.show_form(request, CustomerForm, 'Customer', BASE)


@perm_required('partner.manage')
def create_customer(request):
    return crud.save_form(request, CustomerForm, 'Customer', BASE)


@perm_required('partner.manage')
def edit_customer(request, id):
    return crud.show_form(request, CustomerForm, 'Customer', BASE, get_object_or_404(Customer, pk=id))


@perm_required('partner.manage')
def update_customer(request, id):
    return crud.save_form(request, CustomerForm, 'Customer', BASE, get_object_or_404(Customer, pk=id))


@perm_required('partner.manage')
def delete_customer(request, id):
    return crud.delete_object(request, Customer, id, 'Customer', BASE, 'It is linked to orders - set it to Inactive instead.')
