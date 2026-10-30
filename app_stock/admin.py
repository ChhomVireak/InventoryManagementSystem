from django.contrib import admin

from app_stock.models import Stock, StockBatch, StockTransaction, StockTransactionLine


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('product', 'warehouse', 'quantity_on_hand', 'reserved_quantity')


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = ('product', 'warehouse', 'batch_number', 'expiry_date', 'quantity_on_hand')


class LineInline(admin.TabularInline):
    model = StockTransactionLine
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    """The ledger is read-only everywhere, including Django admin (immutable ledger)."""
    list_display = ('transaction_id', 'transaction_type', 'warehouse', 'user', 'reference_type', 'transaction_date')
    inlines = [LineInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
