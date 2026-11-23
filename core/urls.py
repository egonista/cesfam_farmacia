"""
URLs del módulo Core del Sistema CESFAM Farmacia.
"""
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('simular-rol/<str:rol_key>/', views.simular_rol, name='simular_rol'),
    path('pacientes/', views.paciente_list, name='paciente_list'),
    path('pacientes/crear/', views.paciente_crear, name='paciente_crear'),
    path('pacientes/<int:pk>/', views.paciente_detalle, name='paciente_detalle'),
    path('auditoria/', views.auditoria_list, name='auditoria_list'),
    path('usuarios/', views.usuario_list, name='usuario_list'),
    path('api/validar-rut/', views.api_validar_rut, name='api_validar_rut'),
    path('api/health/', views.api_health, name='api_health'),
    path('api/health', views.api_health, name='api_health_no_slash'),
]
