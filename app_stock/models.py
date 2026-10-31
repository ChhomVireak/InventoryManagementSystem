from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from app_backend.utils import ImmutableModelMixin


class Stock(models.Model):
    stock_id = models.AutoField(primary_key=True)
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='stocks')
    warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='stocks')
    quantity_on_hand = models.IntegerField(default=0)
    reserved_quantity = models.IntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'stock'
        constraints = [
            models.UniqueConstraint(fields=['product', 'warehouse'], name='uniq_stock_product_warehouse'),
            models.CheckConstraint(condition=models.Q(quantity_on_hand__gte=0), name='stock_qty_gte_0'),
            models.CheckConstraint(condition=models.Q(reserved_quantity__gte=0), name='stock_reserved_gte_0'),
        ]

    def __str__(self):
        return f'{self.product.sku} @ {self.warehouse}: {self.quantity_on_hand}'

    @property
    def available(self):
        return self.quantity_on_hand - self.reserved_quantity


class StockBatch(models.Model):
    """FR-16: batch number + expiry per stock receipt."""
    batch_id = models.AutoField(primary_key=True)
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='batches')
    warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='batches')
    batch_number = models.CharField(max_length=50)
    expiry_date = models.DateField(null=True, blank=True)
    quantity_on_hand = models.IntegerField(default=0)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'stock_batch'
        constraints = [
            models.UniqueConstraint(fields=['product', 'warehouse', 'batch_number'], name='uniq_batch'),
            models.CheckConstraint(condition=models.Q(quantity_on_hand__gte=0), name='batch_qty_gte_0'),
        ]

    def __str__(self):
        return f'{self.product.sku} / {self.batch_number}'

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())


class StockTransaction(ImmutableModelMixin):
    """D5 Stock Transactions - immutable ledger of all stock movements (O2)."""
    TYPES = ['IN', 'OUT', 'ADJUSTMENT', 'TRANSFER_IN', 'TRANSFER_OUT', 'RETURN_IN', 'RETURN_OUT']
    REFERENCE_TYPES = ['PO', 'SO', 'TRANSFER', 'RETURN', 'COUNT', 'MANUAL']

    transaction_id = models.AutoField(primary_key=True)
    transaction_type = models.CharField(max_length=30, choices=[(t, t) for t in TYPES])
    warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='transactions')
    user = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='stock_transactions')
    reference_type = models.CharField(max_length=30, choices=[(t, t) for t in REFERENCE_TYPES], default='MANUAL')
    reference_id = models.IntegerField(null=True, blank=True, help_text='ID of related document (application-validated)')
    transaction_date = models.DateTimeField(default=timezone.now)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'stock_transaction'
        ordering = ['-transaction_date', '-transaction_id']

    def __str__(self):
        return f'#{self.pk} {self.transaction_type}'

    @property
    def reference_url(self):
        urls = {'PO': '/purchase/{}/', 'SO': '/sales/{}/', 'TRANSFER': '/stock/transfers/{}/',
                'RETURN': '/returns/{}/', 'COUNT': '/stock/counts/{}/'}
        if self.reference_id and self.reference_type in urls:
            return urls[self.reference_type].format(self.reference_id)
        return ''


class StockTransactionLine(ImmutableModelMixin):
    """Signed quantity: + for stock coming in, - for stock going out."""
    line_id = models.AutoField(primary_key=True)
    transaction = models.ForeignKey(StockTransaction, on_delete=models.PROTECT, related_name='lines')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='stock_lines')
    batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name='lines')
    quantity = models.IntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])

    class Meta:
        db_table = 'stock_transaction_line'
        constraints = [models.CheckConstraint(condition=~models.Q(quantity=0), name='line_qty_not_zero')]


class StockAdjustment(models.Model):
    """FR-08: adjustment with mandatory reason; needs approval above a threshold.
    (Added to the ERD - the analysis requires approval but has no table for the pending request.)"""
    STATUS = [('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected')]

    adjustment_id = models.AutoField(primary_key=True)
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='adjustments')
    warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='adjustments')
    batch_number = models.CharField(max_length=50, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity_change = models.IntegerField(help_text='Positive adds stock, negative removes stock')
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS, default='Pending')
    requested_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='adjustments_requested')
    approved_by = models.ForeignKey('app_accounts.User', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='adjustments_approved')
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'stock_adjustment'
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=~models.Q(quantity_change=0), name='adjustment_not_zero')]


class StockTransfer(models.Model):
    STATUS = [(s, s) for s in ['Pending', 'Approved', 'In Transit', 'Completed', 'Cancelled']]

    transfer_id = models.AutoField(primary_key=True)
    transfer_number = models.CharField(max_length=50, unique=True)
    from_warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='transfers_in')
    created_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='transfers_created')
    approved_by = models.ForeignKey('app_accounts.User', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='transfers_approved')
    transfer_date = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS, default='Pending')
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'stock_transfer'
        ordering = ['-transfer_id']
        constraints = [models.CheckConstraint(condition=~models.Q(from_warehouse=models.F('to_warehouse')),
                                              name='transfer_different_warehouses')]

    def __str__(self):
        return self.transfer_number


class StockTransferItem(models.Model):
    transfer_item_id = models.AutoField(primary_key=True)
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='transfer_items')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        db_table = 'stock_transfer_item'


class StockCount(models.Model):
    STATUS = [(s, s) for s in ['Open', 'Completed', 'Approved']]

    count_id = models.AutoField(primary_key=True)
    count_number = models.CharField(max_length=50, unique=True)
    warehouse = models.ForeignKey('app_warehouse.Warehouse', on_delete=models.PROTECT, related_name='counts')
    performed_by = models.ForeignKey('app_accounts.User', on_delete=models.PROTECT, related_name='counts')
    count_date = models.DateField()
    status = models.CharField(max_length=30, choices=STATUS, default='Open')

    class Meta:
        db_table = 'stock_count'
        ordering = ['-count_id']

    def __str__(self):
        return self.count_number


class StockCountItem(models.Model):
    count_item_id = models.AutoField(primary_key=True)
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('app_product.Product', on_delete=models.PROTECT, related_name='count_items')
    system_quantity = models.IntegerField(validators=[MinValueValidator(0)])
    counted_quantity = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    variance = models.IntegerField(default=0, help_text='counted - system')

    class Meta:
        db_table = 'stock_count_item'
        constraints = [models.UniqueConstraint(fields=['count', 'product'], name='uniq_count_product')]
