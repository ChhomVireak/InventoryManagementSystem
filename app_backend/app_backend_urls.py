from django.urls import path

from app_backend import views

urlpatterns = [
    path('', views.home),
    path('admin_dashboard/', views.dashboard),
]
