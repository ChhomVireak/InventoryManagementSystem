from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from app_accounts import audit
from app_api import serializers as s
from app_api.permissions import RBACPermission
from app_customer.models import Customer
from app_notification.models import Notification
from app_product.models import Category, Product
from app_stock import services
from app_stock.models import Stock, StockTransaction
from app_stock.services import StockError
from app_supplier.models import Supplier
from app_warehouse.models import Warehouse


class AuditedModelViewSet(viewsets.ModelViewSet):
    """CRUD with RBAC + audit log. Search: ?search=  Sort: ?ordering=field  (FR-24)."""
    permission_classes = [RBACPermission]
    search_fields = []

    def get_queryset(self):
        qs = super().get_queryset()
        term = self.request.query_params.get('search')
        if term and self.search_fields:
            q = Q()
            for f in self.search_fields:
                q |= Q(**{f'{f}__icontains': term})
            qs = qs.filter(q)
        ordering = self.request.query_params.get('ordering')
        if ordering and ordering.lstrip('-') in {f.name for f in qs.model._meta.fields}:
            qs = qs.order_by(ordering)
        return qs

    def perform_create(self, serializer):
        obj = serializer.save()
        audit.log_obj(self.request, 'CREATE', obj)

    def perform_update(self, serializer):
        old = audit.snapshot(serializer.instance)
        obj = serializer.save()
        audit.log_obj(self.request, 'UPDATE', obj, old=old)

    def perform_destroy(self, instance):
        old = audit.snapshot(instance)
        pk, table = instance.pk, instance._meta.db_table
        try:
            instance.delete()
        except Exception:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('This record is in use and cannot be deleted - deactivate it instead.')
        audit.log(self.request, 'DELETE', table, pk, old=old)


class CategoryViewSet(AuditedModelViewSet):
    queryset = Category.objects.all()
    serializer_class = s.CategorySerializer
    search_fields = ['name']
    write_permissions = ('product.manage',)


class ProductViewSet(AuditedModelViewSet):
    queryset = Product.objects.select_related('category').all()
    serializer_class = s.ProductSerializer
    search_fields = ['sku', 'name', 'barcode']
    write_permissions = ('product.manage',)


class WarehouseViewSet(AuditedModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = s.WarehouseSerializer
    search_fields = ['name', 'location']
    write_permissions = ('warehouse.manage',)


class SupplierViewSet(AuditedModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = s.SupplierSerializer
    search_fields = ['name', 'email', 'phone']
    write_permissions = ('partner.manage',)


class CustomerViewSet(AuditedModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = s.CustomerSerializer
    search_fields = ['name', 'email', 'phone']
    write_permissions = ('partner.manage',)


class StockViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stock.objects.select_related('product', 'warehouse').all()
    serializer_class = s.StockSerializer
    permission_classes = [RBACPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get('warehouse'):
            qs = qs.filter(warehouse_id=p['warehouse'])
        if p.get('product'):
            qs = qs.filter(product_id=p['product'])
        if p.get('barcode'):
            qs = qs.filter(Q(product__barcode=p['barcode']) | Q(product__sku=p['barcode']))
        return qs.order_by('product__name')


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """The stock ledger is read-only through the API as well (immutable)."""
    queryset = StockTransaction.objects.select_related('user').prefetch_related('lines__product', 'lines__batch')
    serializer_class = s.TransactionSerializer
    permission_classes = [RBACPermission]
    read_permissions = ('stock.in', 'stock.out', 'stock.count', 'stock.adjust.request',
                        'stock.adjust.approve', 'report.view')


class NotificationViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = s.NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


def _movement(request, kind):
    ser = s.MovementSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    try:
        if kind == 'in':
            txn = services.record_in(
                warehouse=d['warehouse'], user=request.user, notes=d['notes'],
                lines=[{'product': d['product'], 'quantity': d['quantity'], 'batch_number': d['batch_number'],
                        'expiry_date': d['expiry_date'], 'unit_cost': d['unit_cost']}])
        else:
            txn = services.record_out(warehouse=d['warehouse'], user=request.user, notes=d['notes'],
                                      lines=[{'product': d['product'], 'quantity': d['quantity']}])
    except StockError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(s.TransactionSerializer(txn).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([RBACPermission])
def stock_in(request):
    return _movement(request, 'in')


stock_in.cls.write_permissions = ('stock.in',)


@api_view(['POST'])
@permission_classes([RBACPermission])
def stock_out(request):
    return _movement(request, 'out')


stock_out.cls.write_permissions = ('stock.out',)
