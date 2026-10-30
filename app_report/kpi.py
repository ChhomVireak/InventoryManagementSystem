"""Section 14 - Key Performance Indicators, computed live from the database (O10)."""
import time
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import DecimalField, ExpressionWrapper, F, Min, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from app_product.models import Product
from app_purchase.models import PurchaseOrder
from app_returns.models import Return
from app_sales.models import SalesOrder
from app_stock.models import Stock, StockBatch, StockCountItem, StockTransaction, StockTransactionLine

MONEY = DecimalField(max_digits=18, decimal_places=2)


def _pct(numerator, denominator):
    return round(float(numerator) / float(denominator) * 100, 2) if denominator else None


def compute():
    started = time.perf_counter()
    today = timezone.localdate()
    kpis = []

    def add(name, definition, value, target, ok=None, unit=''):
        kpis.append({'name': name, 'definition': definition, 'value': value, 'unit': unit,
                     'target': target, 'ok': ok})

    stock_value = Stock.objects.aggregate(v=Coalesce(Sum(ExpressionWrapper(
        F('quantity_on_hand') * F('product__cost_price'), output_field=MONEY)), Decimal('0')))['v']

    # Inventory accuracy = (correct records / total) x 100  (stock counts)
    counted = StockCountItem.objects.filter(count__status__in=['Completed', 'Approved'])
    total_items = counted.count()
    accuracy = _pct(counted.filter(variance=0).count(), total_items)
    add('Inventory Accuracy Rate', '(Correct records / total) x 100', accuracy, '>= 98%',
        None if accuracy is None else accuracy >= 98, '%')

    # Stockout frequency - products with a reorder level that are out of stock now
    products = Product.objects.filter(status='Active').annotate(total=Coalesce(Sum('stocks__quantity_on_hand'), 0))
    stockouts = products.filter(total=0).count()
    add('Stockout Frequency', 'Active products currently at zero stock', stockouts, 'Trending down',
        None if stockouts else True)

    # Overstock value - stock above OVERSTOCK_FACTOR x reorder level
    over = Decimal('0')
    for p in products.filter(reorder_level__gt=0):
        limit = p.reorder_level * settings.OVERSTOCK_FACTOR
        if p.total > limit:
            over += (p.total - limit) * p.cost_price
    add('Overstock Value', f'Value above {settings.OVERSTOCK_FACTOR}x reorder level', over, 'Within policy')

    # Inventory turnover = COGS / average inventory (last 30 days, current value used as average)
    since = timezone.now() - timedelta(days=30)
    cogs = StockTransactionLine.objects.filter(
        transaction__transaction_type='OUT', transaction__transaction_date__gte=since, transaction__reference_type='SO'
    ).aggregate(v=Coalesce(Sum(ExpressionWrapper(-F('quantity') * F('unit_cost'), output_field=MONEY)), Decimal('0')))['v']
    turnover = round(float(cogs) / float(stock_value), 2) if stock_value else None
    add('Inventory Turnover Ratio', 'COGS (30 days) / inventory value', turnover, 'Per category')

    # Order cycle time & supplier lead time = days from PO date to first receipt
    first_receipt = dict(StockTransaction.objects.filter(reference_type='PO', transaction_type='IN')
                         .values_list('reference_id').annotate(first=Min('transaction_date')))
    cycle, per_supplier = [], {}
    for po in PurchaseOrder.objects.filter(pk__in=first_receipt.keys()).select_related('supplier'):
        days = max((timezone.localtime(first_receipt[po.pk]).date() - po.order_date).days, 0)
        cycle.append(days)
        per_supplier.setdefault(po.supplier.name, []).append(days)
    avg_cycle = round(sum(cycle) / len(cycle), 1) if cycle else None
    add('Order Cycle Time', 'PO creation to receipt (days, average)', avg_cycle, 'Per supplier', unit=' days')

    # Shrinkage rate = (book - physical) / book x 100, valued at cost
    book = physical_loss = Decimal('0')
    for item in counted.select_related('product'):
        book += item.system_quantity * item.product.cost_price
        if item.variance < 0:
            physical_loss += -item.variance * item.product.cost_price
    shrink = _pct(physical_loss, book)
    add('Shrinkage Rate', '(Book - physical) / book x 100', shrink, '<= policy', unit='%')

    lead = [{'supplier': k, 'orders': len(v), 'avg_days': round(sum(v) / len(v), 1)}
            for k, v in sorted(per_supplier.items())]
    add('Supplier Lead Time', 'Days from PO to receipt (see table below)', avg_cycle, 'Per supplier', unit=' days')

    # Order fulfilment rate = orders shipped complete / total
    live = SalesOrder.objects.filter(status__in=['Confirmed', 'Shipped', 'Delivered'])
    fulfil = _pct(live.filter(status__in=['Shipped', 'Delivered']).count(), live.count())
    add('Order Fulfillment Rate', 'Orders shipped complete / total', fulfil, '>= 95%',
        None if fulfil is None else fulfil >= 95, '%')

    # Return rate = returns / orders
    orders = (PurchaseOrder.objects.exclude(status__in=['Draft', 'Cancelled']).count()
              + SalesOrder.objects.exclude(status__in=['Draft', 'Cancelled']).count())
    returns = Return.objects.exclude(status='Cancelled').count()
    add('Return Rate', 'Returns / orders', _pct(returns, orders), 'Trending down', unit='%')

    # Expiry / wastage rate = expired value / total stock value
    expired_value = StockBatch.objects.filter(expiry_date__lt=today, quantity_on_hand__gt=0).aggregate(
        v=Coalesce(Sum(ExpressionWrapper(F('quantity_on_hand') * F('product__cost_price'), output_field=MONEY)),
                   Decimal('0')))['v']
    add('Expiry/Wastage Rate', 'Expired value / total stock value', _pct(expired_value, stock_value), '<= policy',
        unit='%')

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    add('Report Generation Time', 'Time to compute this KPI page', elapsed_ms, '<= 5 seconds',
        elapsed_ms <= 5000, ' ms')
    return {'kpis': kpis, 'lead_times': lead, 'stock_value': stock_value}
