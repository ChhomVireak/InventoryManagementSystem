from django.urls import path

from app_sales import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_sales),
    path('create', views.create_sales),
    path('edit/<int:id>', views.edit_sales),
    path('update/<int:id>', views.update_sales),
    path('delete/<int:id>', views.delete_sales),
    path('<int:id>/', views.detail),
    path('<int:id>/dispatch', views.dispatch),
    path('<int:id>/<str:name>', views.action),
]
