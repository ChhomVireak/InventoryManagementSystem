from django.urls import path

from app_product import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_product),
    path('create', views.create_product),
    path('edit/<int:id>', views.edit_product),
    path('update/<int:id>', views.update_product),
    path('delete/<int:id>', views.delete_product),
    path('lookup/', views.lookup),
    path('search/', views.search),
    path('category/', views.category_index),
    path('category/formcreate', views.show_category),
    path('category/create', views.create_category),
    path('category/edit/<int:id>', views.edit_category),
    path('category/update/<int:id>', views.update_category),
    path('category/delete/<int:id>', views.delete_category),
]
