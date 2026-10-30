from django.contrib import admin
from django.urls import path, include

handler403 = 'app_backend.views.permission_denied'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('app_backend.app_backend_urls')),
    path('', include('app_accounts.app_accounts_urls')),
    path('product/', include('app_product.app_product_urls')),
    path('warehouse/', include('app_warehouse.app_warehouse_urls')),
    path('supplier/', include('app_supplier.app_supplier_urls')),
    path('customer/', include('app_customer.app_customer_urls')),
    path('stock/', include('app_stock.app_stock_urls')),
    path('purchase/', include('app_purchase.app_purchase_urls')),
    path('sales/', include('app_sales.app_sales_urls')),
    path('returns/', include('app_returns.app_returns_urls')),
    path('notification/', include('app_notification.app_notification_urls')),
    path('report/', include('app_report.app_report_urls')),
    path('api/', include('app_api.app_api_urls')),
]
