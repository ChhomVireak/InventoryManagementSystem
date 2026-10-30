from django import forms

from app_backend.forms import BootstrapFormMixin
from app_supplier.models import Supplier


class SupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_person', 'email', 'phone', 'address', 'status']
