from django.urls import path

from app_returns import views

urlpatterns = [
    path('', views.index),
    path('new', views.new),
    path('<int:id>/', views.detail),
    path('<int:id>/<str:name>', views.action),
]
