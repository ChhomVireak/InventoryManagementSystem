from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class SalesOrder(models.Model):
    """D7 Sales Orders (header)."""
    STATUS = [(s, s) for s in ['Draft', 'Confirmed', 'Shipped', 'Delivered', 'Cancelled']]

    so_id = models.AutoField(primary_key=True)
    so_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey('app_customer.Customer', on_delete=models.PROTECT, related_name='sales_orders')
    created_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='sales_orders')
    order_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS, default='Draft')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'sales_order'
        ordering = ['-so_id']

    def __str__(self):
        return self.so_number

    @property
    def subtotal(self):
        return sum((i.line_total for i in self.items.all()), Decimal('0'))

    @property
    def can_edit(self):
        return self.status == 'Draft'

    def recalculate(self):
        """total = subtotal - discount + tax, where tax = SALES_TAX_RATE x (subtotal - discount)."""
        from django.conf import settings
        taxable = max(self.subtotal - self.discount_amount, Decimal('0'))
        self.tax_amount = (taxable * settings.SALES_TAX_RATE).quantize(Decimal('0.01'))
        self.total_amount = taxable + self.tax_amount
        self.save(update_fields=['tax_amount', 'total_amount'])


class SalesOrderItem(models.Model):
    so_item_id = models.AutoField(primary_key=True)
    so = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='so_items')
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_shipped = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'sales_order_item'
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_shipped__lte=models.F('quantity_ordered')),
                                   name='so_item_shipped_lte_ordered'),
        ]

    def save(self, *args, **kwargs):
        self.line_total = self.quantity_ordered * self.unit_price
        super().save(*args, **kwargs)

    @property
    def remaining(self):
        return self.quantity_ordered - self.quantity_shipped
