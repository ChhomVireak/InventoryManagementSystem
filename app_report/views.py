"""Process 5.0 - Generate Reports (FR-19). Every report can be exported to CSV."""
import csv
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import Http404, render
from django.utils import timezone

from app_accounts.decorators import perm_required
from app_product.models import Category
from app_purchase.models import PurchaseOrder
from app_report import kpi
from app_returns.models import Return
from app_sales.models import SalesOrder
from app_stock.models import Stock, StockBatch, StockTransactionLine
from app_stock.services import low_stock_products
from app_supplier.models import Supplier
from app_warehouse.models import Warehouse

MONEY = DecimalField(max_digits=18, decimal_places=2)

CATALOGUE = [
    ('inventory', 'Inventory report', 'Quantity on hand, reserved and available for every product / warehouse', 'fa-boxes'),
    ('low-stock', 'Low-stock report', 'Products at or below their reorder level', 'fa-exclamation-triangle'),
    ('valuation', 'Inventory valuation', 'Stock value (quantity x cost price) per warehouse and category', 'fa-coins'),
    ('expiry', 'Expiry report', 'Batches that are expired or expiring soon', 'fa-hourglass-end'),
    ('purchases', 'Purchase report', 'Purchase orders by date, supplier and status', 'fa-shopping-cart'),
    ('sales', 'Sales report', 'Sales orders by date and status', 'fa-cash-register'),
    ('returns', 'Returns report', 'Purchase and sales returns', 'fa-undo'),
    ('movements', 'Stock movement ledger', 'Every stock transaction line (audit of quantities)', 'fa-exchange-alt'),
]


def _date_filters(request):
    return request.GET.get('from', ''), request.GET.get('to', '')


def r_inventory(request):
    qs = Stock.objects.select_related('product', 'warehouse', 'product__category').order_by('product__name')
    if request.GET.get('warehouse'):
        qs = qs.filter(warehouse_id=request.GET['warehouse'])
    if request.GET.get('category'):
        qs = qs.filter(product__category_id=request.GET['category'])
    rows = [[s.product.sku, s.product.name, s.product.category.name, s.warehouse.name, s.quantity_on_hand,
             s.reserved_quantity, s.available, s.product.reorder_level, s.product.cost_price,
             s.quantity_on_hand * s.product.cost_price] for s in qs]
    cols = ['SKU', 'Product', 'Category', 'Warehouse', 'On hand', 'Reserved', 'Available', 'Reorder level',
            'Unit cost', 'Value']
    total = sum((r[-1] for r in rows), Decimal('0'))
    return 'Inventory report', cols, rows, f'Total value: {total:,.2f}', ['warehouse', 'category']


def r_low_stock(request):
    rows = [[p.sku, p.name, p.category.name, p.total, p.reorder_level, p.reorder_level - p.total + 1]
            for p in low_stock_products()]
    return ('Low-stock report', ['SKU', 'Product', 'Category', 'Total on hand', 'Reorder level',
                                 'Suggested order qty (min)'], rows, f'{len(rows)} product(s) need reordering', [])


def r_valuation(request):
    qs = Stock.objects.values('warehouse__name', 'product__category__name').annotate(
        units=Sum('quantity_on_hand'),
        value=Coalesce(Sum(ExpressionWrapper(F('quantity_on_hand') * F('product__cost_price'), output_field=MONEY)),
                       Decimal('0'))).order_by('warehouse__name', 'product__category__name')
    if request.GET.get('warehouse'):
        qs = qs.filter(warehouse_id=request.GET['warehouse'])
    rows = [[r['warehouse__name'], r['product__category__name'], r['units'], r['value']] for r in qs]
    total = sum((r[3] for r in rows), Decimal('0'))
    return ('Inventory valuation', ['Warehouse', 'Category', 'Units', 'Value (cost)'], rows,
            f'Total inventory value: {total:,.2f}', ['warehouse'])


def r_expiry(request):
    days = int(request.GET.get('days') or 30)
    today = timezone.localdate()
    qs = (StockBatch.objects.filter(quantity_on_hand__gt=0, expiry_date__isnull=False,
                                    expiry_date__lte=today + timedelta(days=days))
          .select_related('product', 'warehouse').order_by('expiry_date'))
    if request.GET.get('warehouse'):
        qs = qs.filter(warehouse_id=request.GET['warehouse'])
    rows = [[b.product.sku, b.product.name, b.batch_number, b.warehouse.name, b.expiry_date,
             (b.expiry_date - today).days, b.quantity_on_hand, b.quantity_on_hand * b.product.cost_price,
             'EXPIRED' if b.expiry_date < today else 'Expiring'] for b in qs]
    return ('Expiry report', ['SKU', 'Product', 'Batch', 'Warehouse', 'Expiry date', 'Days left', 'Qty', 'Value',
                              'State'], rows, f'Batches expiring within {days} days or already expired',
            ['warehouse', 'days'])


def _orders(qs, request, number_field, party_field, date_field):
    date_from, date_to = _date_filters(request)
    if date_from:
        qs = qs.filter(**{f'{date_field}__gte': date_from})
    if date_to:
        qs = qs.filter(**{f'{date_field}__lte': date_to})
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    return qs


def r_purchases(request):
    qs = _orders(PurchaseOrder.objects.select_related('supplier'), request, 'po_number', 'supplier', 'order_date')
    if request.GET.get('supplier'):
        qs = qs.filter(supplier_id=request.GET['supplier'])
    rows = [[o.po_number, o.supplier.name, o.order_date, o.expected_date or '', o.status, o.items.count(),
             o.discount_amount, o.total_amount] for o in qs.order_by('-order_date')]
    total = sum((r[-1] for r in rows if r[4] != 'Cancelled'), Decimal('0'))
    return ('Purchase report', ['PO number', 'Supplier', 'Order date', 'Expected', 'Status', 'Lines', 'Discount',
                                'Total'], rows, f'Total (excl. cancelled): {total:,.2f}',
            ['from', 'to', 'status', 'supplier'])


def r_sales(request):
    qs = _orders(SalesOrder.objects.select_related('customer'), request, 'so_number', 'customer', 'order_date')
    rows = [[o.so_number, o.customer.name, o.order_date, o.status, o.items.count(), o.discount_amount,
             o.tax_amount, o.total_amount] for o in qs.order_by('-order_date')]
    total = sum((r[-1] for r in rows if r[3] != 'Cancelled'), Decimal('0'))
    return ('Sales report', ['SO number', 'Customer', 'Order date', 'Status', 'Lines', 'Discount', 'Tax', 'Total'],
            rows, f'Total (excl. cancelled): {total:,.2f}', ['from', 'to', 'status'])


def r_returns(request):
    qs = Return.objects.select_related('created_by').prefetch_related('items')
    date_from, date_to = _date_filters(request)
    if date_from:
        qs = qs.filter(return_date__gte=date_from)
    if date_to:
        qs = qs.filter(return_date__lte=date_to)
    rows = [[r.return_number, r.get_return_type_display(), r.order_number, r.return_date, r.status,
             sum(i.quantity for i in r.items.all()), sum(i.quantity * i.unit_price for i in r.items.all()), r.reason]
            for r in qs]
    return ('Returns report', ['Return', 'Type', 'Order', 'Date', 'Status', 'Units', 'Value', 'Reason'], rows,
            f'{len(rows)} return(s)', ['from', 'to'])


def r_movements(request):
    qs = StockTransactionLine.objects.select_related('transaction__warehouse', 'transaction__user', 'product', 'batch')
    date_from, date_to = _date_filters(request)
    if date_from:
        qs = qs.filter(transaction__transaction_date__date__gte=date_from)
    if date_to:
        qs = qs.filter(transaction__transaction_date__date__lte=date_to)
    if request.GET.get('warehouse'):
        qs = qs.filter(transaction__warehouse_id=request.GET['warehouse'])
    rows = [[timezone.localtime(l.transaction.transaction_date).strftime('%Y-%m-%d %H:%M'), l.transaction_id,
             l.transaction.transaction_type, l.transaction.warehouse.name, l.product.sku, l.product.name,
             l.batch.batch_number if l.batch else '', l.quantity, l.unit_cost,
             f'{l.transaction.reference_type} {l.transaction.reference_id or ""}'.strip(),
             l.transaction.user.username]
            for l in qs.order_by('-transaction__transaction_date', '-pk')[:5000]]
    return ('Stock movement ledger', ['Date', 'Txn', 'Type', 'Warehouse', 'SKU', 'Product', 'Batch', 'Qty',
                                      'Unit cost', 'Reference', 'User'], rows,
            'Showing the latest 5,000 lines', ['from', 'to', 'warehouse'])


REPORTS = {'inventory': r_inventory, 'low-stock': r_low_stock, 'valuation': r_valuation, 'expiry': r_expiry,
           'purchases': r_purchases, 'sales': r_sales, 'returns': r_returns, 'movements': r_movements}


@perm_required('report.view')
def index(request):
    return render(request, 'pages/report/index.html', {'catalogue': CATALOGUE})


@perm_required('report.view')
def show(request, slug):
    if slug not in REPORTS:
        raise Http404
    title, columns, rows, summary, filters = REPORTS[slug](request)
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{slug}-{timezone.localdate()}.csv"'
        writer = csv.writer(response)
        writer.writerow(columns)
        writer.writerows(rows)
        return response
    params = request.GET.copy()
    params.pop('export', None)
    return render(request, 'pages/report/show.html', {
        'slug': slug, 'title': title, 'columns': columns, 'rows': rows[:1000], 'row_count': len(rows),
        'summary': summary, 'filters': filters, 'warehouses': Warehouse.objects.all(),
        'categories': Category.objects.all(), 'suppliers': Supplier.objects.all(),
        'statuses': {'purchases': [s for s, _ in PurchaseOrder.STATUS], 'sales': [s for s, _ in SalesOrder.STATUS]}.get(slug, []),
        'qs': params.urlencode(), 'get': request.GET})


@perm_required('report.view')
def kpi_page(request):
    return render(request, 'pages/report/kpi.html', kpi.compute())
