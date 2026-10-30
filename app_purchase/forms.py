from decimal import Decimal

from django import forms

from app_backend.forms import BootstrapFormMixin
from app_purchase.models import PurchaseOrder
from app_supplier.models import Supplier


class PurchaseOrderForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ['supplier', 'order_date', 'expected_date', 'discount_amount', 'notes']
        widgets = {'order_date': forms.DateInput(format='%Y-%m-%d'),
                   'expected_date': forms.DateInput(format='%Y-%m-%d'),
                   'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].queryset = Supplier.objects.filter(status='Active')
        self.fields['discount_amount'].required = False

    def clean_discount_amount(self):
        return self.cleaned_data.get('discount_amount') or Decimal('0')

    def clean(self):
        data = super().clean()
        if data.get('expected_date') and data.get('order_date') and data['expected_date'] < data['order_date']:
            self.add_error('expected_date', 'Expected date cannot be before the order date.')
        if data.get('discount_amount') is not None and data['discount_amount'] < 0:
            self.add_error('discount_amount', 'Discount cannot be negative.')
        return data
