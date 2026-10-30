from django import forms

from app_backend.forms import BootstrapFormMixin
from app_warehouse.models import Warehouse


class WarehouseForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ['name', 'location', 'address', 'status']
