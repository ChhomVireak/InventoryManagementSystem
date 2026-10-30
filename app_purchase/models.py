from django.core.validators import MinValueValidator
from django.db import models


class PurchaseOrder(models.Model):
    """D6 Purchase Orders (header)."""
    STATUS = [(s, s) for s in ['Draft', 'Sent', 'Partial', 'Received', 'Cancelled']]

    po_id = models.AutoField(primary_key=True)
    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey('app_supplier.Supplier', on_delete=models.PROTECT, related_name='purchase_orders')
    created_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='purchase_orders')
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=STATUS, default='Draft')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_order'
        ordering = ['-po_id']

    def __str__(self):
        return self.po_number

    @property
    def subtotal(self):
        return self.total_amount + self.discount_amount

    @property
    def can_edit(self):
        return self.status == 'Draft'

    def recalculate(self):
        subtotal = sum(i.line_total for i in self.items.all())
        self.total_amount = max(subtotal - self.discount_amount, 0)
        self.save(update_fields=['total_amount'])


class PurchaseOrderItem(models.Model):
    po_item_id = models.AutoField(primary_key=True)
    po = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='po_items')
    quantity_ordered = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    quantity_received = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = 'purchase_order_item'
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity_received__lte=models.F('quantity_ordered')),
                                   name='po_item_received_lte_ordered'),
        ]

    def save(self, *args, **kwargs):
        self.line_total = self.quantity_ordered * self.unit_price      # quantity_ordered x unit_price
        super().save(*args, **kwargs)

    @property
    def remaining(self):
        return self.quantity_ordered - self.quantity_received
