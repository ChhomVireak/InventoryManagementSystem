import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, F, Sum, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import redirect, render
from django.utils import timezone

from app_notification.services import sync_expiry_alerts
from app_product.models import Product
from app_purchase.models import PurchaseOrder
from app_sales.models import SalesOrder
from app_stock.models import Stock, StockBatch, StockTransactionLine, StockAdjustment, StockTransfer, StockCount
from app_stock.services import low_stock_products
from app_warehouse.models import Warehouse


def home(request):
    return redirect('/admin_dashboard/')


def permission_denied(request, exception=None):
    return render(request, '403.html', status=403)


def dashboard(request):
    """FR-20: dashboard of key inventory metrics (computed live on every request)."""
    sync_expiry_alerts()
    today = timezone.localdate()
    value = ExpressionWrapper(F('quantity_on_hand') * F('product__cost_price'),
                              output_field=DecimalField(max_digits=18, decimal_places=2))
    stock_value = Stock.objects.aggregate(v=Coalesce(Sum(value), Decimal('0')))['v']
    low = low_stock_products()
    expiring = StockBatch.objects.filter(
        quantity_on_hand__gt=0, expiry_date__isnull=False,
        expiry_date__lte=today + timedelta(days=settings.EXPIRY_ALERT_DAYS))

    # Last 7 days of stock movement for the chart
    start = timezone.now() - timedelta(days=6)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    lines = StockTransactionLine.objects.filter(transaction__transaction_date__gte=start)
    ins = dict(lines.filter(quantity__gt=0).annotate(d=TruncDate('transaction__transaction_date'))
               .values_list('d').annotate(t=Sum('quantity')))
    outs = dict(lines.filter(quantity__lt=0).annotate(d=TruncDate('transaction__transaction_date'))
                .values_list('d').annotate(t=Sum('quantity')))
    days = [(start + timedelta(days=i)).date() for i in range(7)]
    chart = {
        'labels': [d.strftime('%d %b') for d in days],
        'in': [int(ins.get(d, 0)) for d in days],
        'out': [abs(int(outs.get(d, 0))) for d in days],
    }
    top = (Stock.objects.values('product__name').annotate(q=Sum('quantity_on_hand'))
           .order_by('-q')[:5])

    return render(request, 'pages/dashboard/dashboard.html', {
        'product_count': Product.objects.filter(status='Active').count(),
        'warehouse_count': Warehouse.objects.filter(status='Active').count(),
        'stock_value': stock_value,
        'low_stock': low[:8], 'low_stock_count': len(low),
        'expiring': expiring.select_related('product', 'warehouse').order_by('expiry_date')[:8],
        'expiring_count': expiring.count(),
        'open_po': PurchaseOrder.objects.filter(status__in=['Draft', 'Sent', 'Partial']).count(),
        'open_so': SalesOrder.objects.filter(status__in=['Draft', 'Confirmed']).count(),
        'pending_approvals': (StockAdjustment.objects.filter(status='Pending').count()
                              + StockTransfer.objects.filter(status='Pending').count()
                              + StockCount.objects.filter(status='Completed').count()),
        'recent_lines': (StockTransactionLine.objects.select_related(
            'transaction__warehouse', 'product', 'transaction__user')
            .order_by('-transaction__transaction_date', '-pk')[:8]),
        'chart_json': json.dumps(chart),
        'top_json': json.dumps({'labels': [t['product__name'] for t in top], 'data': [int(t['q']) for t in top]}),
    })
