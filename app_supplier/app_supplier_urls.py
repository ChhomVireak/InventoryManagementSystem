from django.urls import path

from app_supplier import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_supplier),
    path('create', views.create_supplier),
    path('edit/<int:id>', views.edit_supplier),
    path('update/<int:id>', views.update_supplier),
    path('delete/<int:id>', views.delete_supplier),
]
