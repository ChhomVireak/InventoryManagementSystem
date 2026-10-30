from django.urls import path

from app_accounts import views

urlpatterns = [
    path('login/', views.login_view),
    path('logout/', views.logout_view),
    path('users/', views.user_index),
    path('users/formcreate', views.user_formcreate),
    path('users/create', views.user_create),
    path('users/edit/<int:id>', views.user_edit),
    path('users/update/<int:id>', views.user_update),
    path('users/delete/<int:id>', views.user_delete),
    path('users/roles/', views.role_index),
    path('users/roles/edit/<int:id>', views.role_edit),
    path('users/roles/update/<int:id>', views.role_update),
    path('audit/', views.audit_index),
]
