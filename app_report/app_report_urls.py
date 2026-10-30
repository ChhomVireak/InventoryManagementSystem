from django.urls import path

from app_report import views

urlpatterns = [
    path('', views.index),
    path('kpi/', views.kpi_page),
    path('<slug:slug>/', views.show),
]
