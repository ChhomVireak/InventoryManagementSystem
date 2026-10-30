from django.urls import path

from app_customer import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_customer),
    path('create', views.create_customer),
    path('edit/<int:id>', views.edit_customer),
    path('update/<int:id>', views.update_customer),
    path('delete/<int:id>', views.delete_customer),
]
