from rest_framework import serializers

from app_customer.models import Customer
from app_notification.models import Notification
from app_product.models import Category, Product
from app_stock.models import Stock, StockTransaction, StockTransactionLine
from app_supplier.models import Supplier
from app_warehouse.models import Warehouse


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = '__all__'


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = '__all__'


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'


class StockSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='product.sku', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    warehouse_name = serializers.CharField(source='warehouse.name', read_only=True)
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = Stock
        fields = ['stock_id', 'product', 'sku', 'product_name', 'warehouse', 'warehouse_name',
                  'quantity_on_hand', 'reserved_quantity', 'available', 'last_updated']


class TransactionLineSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source='product.sku', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True, default=None)

    class Meta:
        model = StockTransactionLine
        fields = ['line_id', 'product', 'sku', 'batch', 'batch_number', 'quantity', 'unit_cost']


class TransactionSerializer(serializers.ModelSerializer):
    lines = TransactionLineSerializer(many=True, read_only=True)
    user_name = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = StockTransaction
        fields = ['transaction_id', 'transaction_type', 'warehouse', 'user_name', 'reference_type', 'reference_id',
                  'transaction_date', 'notes', 'lines']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['notification_id', 'type', 'message', 'is_read', 'created_at']
        read_only_fields = ['type', 'message', 'created_at']


class MovementSerializer(serializers.Serializer):
    """Body for POST /api/stock/in/ and /api/stock/out/"""
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.filter(status='Active'))
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    batch_number = serializers.CharField(required=False, allow_blank=True, default='')
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True,
                                         default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default='')
