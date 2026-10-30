from django import forms

from app_backend.forms import BootstrapFormMixin
from app_customer.models import Customer


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'email', 'phone', 'address', 'status']
