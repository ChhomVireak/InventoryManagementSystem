from django.urls import path

from app_purchase import views

urlpatterns = [
    path('', views.index),
    path('formcreate', views.show_purchase),
    path('create', views.create_purchase),
    path('edit/<int:id>', views.edit_purchase),
    path('update/<int:id>', views.update_purchase),
    path('delete/<int:id>', views.delete_purchase),
    path('<int:id>/', views.detail),
    path('<int:id>/receive', views.receive),
    path('<int:id>/<str:name>', views.action),
]
