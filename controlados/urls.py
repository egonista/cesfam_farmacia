"""
URLs del módulo Controlados del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'controlados'

urlpatterns = [
    path('libro/', views.libro, name='libro'),
    path('libro/registro/', views.registro_controlado, name='registro'),
    path('verificar-2fa/', views.verificar_2fa, name='verificar_2fa'),
]
