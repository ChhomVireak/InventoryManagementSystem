from django.urls import path

from app_warehouse import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_warehouse),
    path('create', views.create_warehouse),
    path('edit/<int:id>', views.edit_warehouse),
    path('update/<int:id>', views.update_warehouse),
    path('delete/<int:id>', views.delete_warehouse),
]
