from django.core.validators import MinValueValidator
from django.db import models


class Return(models.Model):
    """FR-15: purchase return or sales return, always linked to the original order."""
    TYPES = [('PURCHASE_RETURN', 'Purchase return'), ('SALES_RETURN', 'Sales return')]
    ORDER_TYPES = [('PURCHASE_ORDER', 'Purchase order'), ('SALES_ORDER', 'Sales order')]
    STATUS = [(s, s) for s in ['Pending', 'Approved', 'Completed', 'Cancelled']]

    return_id = models.AutoField(primary_key=True)
    return_number = models.CharField(max_length=50, unique=True)
    return_type = models.CharField(max_length=20, choices=TYPES)
    reference_order_type = models.CharField(max_length=20, choices=ORDER_TYPES)
    reference_order_id = models.IntegerField()
    created_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='returns')
    return_date = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS, default='Pending')
    reason = models.CharField(max_length=255)

    class Meta:
        db_table = 'returns'
        ordering = ['-return_id']

    def __str__(self):
        return self.return_number

    @property
    def order(self):
        """The referenced purchase / sales order (application-validated FK)."""
        if self.reference_order_type == 'PURCHASE_ORDER':
            from app_purchase.models import PurchaseOrder
            return PurchaseOrder.objects.filter(pk=self.reference_order_id).first()
        from app_sales.models import SalesOrder
        return SalesOrder.objects.filter(pk=self.reference_order_id).first()

    @property
    def order_number(self):
        order = self.order
        return (order.po_number if self.reference_order_type == 'PURCHASE_ORDER' else order.so_number) if order else '?'

    @property
    def order_url(self):
        base = '/purchase/' if self.reference_order_type == 'PURCHASE_ORDER' else '/sales/'
        return f'{base}{self.reference_order_id}/'


class ReturnItem(models.Model):
    CONDITIONS = [('Restockable', 'Restockable'), ('Damaged', 'Damaged')]

    return_item_id = models.AutoField(primary_key=True)
    return_order = models.ForeignKey(Return, on_delete=models.CASCADE, related_name='items', db_column='return_id')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='return_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    condition = models.CharField(max_length=20, choices=CONDITIONS, default='Restockable')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        db_table = 'return_item'
