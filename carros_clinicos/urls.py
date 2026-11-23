"""
URLs del módulo Carros Clínicos del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'carros_clinicos'

urlpatterns = [
    path('', views.carro_list, name='carro_list'),
    path('<int:pk>/', views.carro_detalle, name='carro_detalle'),
    path('<int:pk>/consumo/', views.registrar_consumo, name='registrar_consumo'),
    path('<int:pk>/reponer/', views.reponer_carro, name='reponer_carro'),
]
