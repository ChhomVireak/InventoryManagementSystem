from django import forms

from app_backend.forms import BootstrapFormMixin
from app_product.models import Category, Product

UNITS = ['pcs', 'kg', 'g', 'box', 'carton', 'pack', 'bottle', 'litre', 'metre', 'set']


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ['sku', 'name', 'category', 'unit_of_measure', 'cost_price', 'selling_price', 'reorder_level',
                  'barcode', 'is_batch_tracked', 'is_expiry_tracked', 'status', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}),
                   'unit_of_measure': forms.TextInput(attrs={'list': 'uom-list'})}

    def clean_sku(self):
        return self.cleaned_data['sku'].strip().upper()

    def clean(self):
        data = super().clean()
        if self.instance.pk and data.get('is_batch_tracked') is False and self.instance.is_batch_tracked:
            if self.instance.stocks.filter(quantity_on_hand__gt=0).exists():
                self.add_error('is_batch_tracked', 'Cannot turn off batch tracking while stock exists.')
        return data
