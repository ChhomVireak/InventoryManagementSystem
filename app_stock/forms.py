from django import forms

from app_backend.forms import BootstrapFormMixin
from app_product.models import Product
from app_warehouse.models import Warehouse


class ProductPicker(forms.Select):
    """Select2/AJAX product picker: only the selected option is rendered, so the page stays
    light with 10,000+ products (NFR-01, NFR-11). Options are searched via /product/search/."""

    def __init__(self, attrs=None):
        base = {'class': 'form-control js-product', 'data-url': '/product/search/'}
        base.update(attrs or {})
        super().__init__(attrs=base)

    def optgroups(self, name, value, attrs=None):
        groups = [(None, [self.create_option(name, '', '---------', False, 0)], 0)]
        selected = [v for v in (value or []) if v not in (None, '')]
        if selected:
            product = Product.objects.filter(pk=selected[0]).first()
            if product:
                groups.append((None, [self.create_option(name, product.pk, str(product), True, 1, attrs=attrs)], 1))
        return groups


class ProductChoiceField(forms.ModelChoiceField):
    def __init__(self, **kwargs):
        super().__init__(queryset=Product.objects.all(), widget=ProductPicker(), **kwargs)


def active_warehouses():
    return Warehouse.objects.filter(status='Active')


class StockInForm(BootstrapFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    product = ProductChoiceField()
    quantity = forms.IntegerField(min_value=1)
    batch_number = forms.CharField(max_length=50, required=False, help_text='Required for batch / expiry tracked products')
    expiry_date = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d'))
    unit_cost = forms.DecimalField(min_value=0, max_digits=12, decimal_places=2, required=False,
                                   help_text='Blank = product cost price')
    reference = forms.CharField(max_length=150, required=False, label='Reference document',
                                help_text='e.g. delivery note / invoice number')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = active_warehouses()


class StockOutForm(BootstrapFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    product = ProductChoiceField()
    quantity = forms.IntegerField(min_value=1)
    reference = forms.CharField(max_length=150, required=False, label='Reference document / reason')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = active_warehouses()


class AdjustmentForm(BootstrapFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    product = ProductChoiceField()
    quantity_change = forms.IntegerField(help_text='Positive adds stock, negative removes stock')
    batch_number = forms.CharField(max_length=50, required=False, help_text='Only needed when adding batch-tracked stock')
    expiry_date = forms.DateField(required=False, widget=forms.DateInput(format='%Y-%m-%d'))
    reason = forms.CharField(max_length=255, label='Reason (mandatory)')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = active_warehouses()

    def clean_quantity_change(self):
        qty = self.cleaned_data['quantity_change']
        if qty == 0:
            raise forms.ValidationError('Quantity change cannot be zero.')
        return qty

    def clean_reason(self):
        reason = self.cleaned_data['reason'].strip()
        if not reason:
            raise forms.ValidationError('A reason is required.')
        return reason


class TransferForm(BootstrapFormMixin, forms.Form):
    from_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    to_warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    transfer_date = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d'))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['from_warehouse'].queryset = active_warehouses()
        self.fields['to_warehouse'].queryset = active_warehouses()

    def clean(self):
        data = super().clean()
        if data.get('from_warehouse') and data.get('from_warehouse') == data.get('to_warehouse'):
            self.add_error('to_warehouse', 'Destination must differ from the source warehouse.')
        return data


class CountForm(BootstrapFormMixin, forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none())
    count_date = forms.DateField(widget=forms.DateInput(format='%Y-%m-%d'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = active_warehouses()
