from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from app_api import views

router = DefaultRouter()
router.register('categories', views.CategoryViewSet)
router.register('products', views.ProductViewSet)
router.register('warehouses', views.WarehouseViewSet)
router.register('suppliers', views.SupplierViewSet)
router.register('customers', views.CustomerViewSet)
router.register('stock', views.StockViewSet)
router.register('transactions', views.TransactionViewSet)
router.register('notifications', views.NotificationViewSet, basename='notification')

urlpatterns = [
    path('token/', TokenObtainPairView.as_view()),          # JWT access + refresh
    path('token/refresh/', TokenRefreshView.as_view()),
    path('stock-in/', views.stock_in),
    path('stock-out/', views.stock_out),
    path('', include(router.urls)),
]
