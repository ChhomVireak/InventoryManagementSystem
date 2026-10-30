from django.urls import path

from app_notification import views

urlpatterns = [
    path('', views.index),
    path('read/<int:id>', views.mark_read),
    path('read-all', views.mark_all_read),
]
