from decimal import Decimal

from django import forms

from app_backend.forms import BootstrapFormMixin
from app_customer.models import Customer
from app_sales.models import SalesOrder


class SalesOrderForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SalesOrder
        fields = ['customer', 'order_date', 'delivery_date', 'discount_amount', 'notes']
        widgets = {'order_date': forms.DateInput(format='%Y-%m-%d'),
                   'delivery_date': forms.DateInput(format='%Y-%m-%d'),
                   'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(status='Active')
        self.fields['discount_amount'].required = False

    def clean_discount_amount(self):
        return self.cleaned_data.get('discount_amount') or Decimal('0')

    def clean(self):
        data = super().clean()
        if data.get('delivery_date') and data.get('order_date') and data['delivery_date'] < data['order_date']:
            self.add_error('delivery_date', 'Delivery date cannot be before the order date.')
        if data.get('discount_amount') is not None and data['discount_amount'] < 0:
            self.add_error('discount_amount', 'Discount cannot be negative.')
        return data
