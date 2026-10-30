from django.urls import path

from app_stock import views

urlpatterns = [
    path('', views.index),
    path('in/', views.stock_in),
    path('out/', views.stock_out),
    path('transactions/', views.transactions),
    path('transactions/<int:id>/', views.transaction_detail),
    path('batches/', views.batches),
    path('adjustments/', views.adjustment_index),
    path('adjustments/new', views.adjustment_new),
    path('adjustments/<int:id>/<str:decision>', views.adjustment_decide),
    path('transfers/', views.transfer_index),
    path('transfers/new', views.transfer_new),
    path('transfers/<int:id>/', views.transfer_detail),
    path('transfers/<int:id>/<str:action>', views.transfer_action),
    path('counts/', views.count_index),
    path('counts/new', views.count_new),
    path('counts/<int:id>/', views.count_detail),
    path('counts/<int:id>/<str:action>', views.count_action),
]
