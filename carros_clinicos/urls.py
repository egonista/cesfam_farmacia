"""
URLs del módulo Carros Clínicos del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'carros_clinicos'

urlpatterns = [
    path('', views.carro_list, name='carro_list'),
    path('<int:pk>/', views.carro_detalle, name='carro_detalle'),
    path('<int:pk>/editar/', views.carro_editar, name='carro_editar'),
    path('<int:pk>/eliminar/', views.carro_eliminar, name='carro_eliminar'),
    path('<int:pk>/items/<int:item_pk>/editar/', views.item_plantilla_editar, name='item_plantilla_editar'),
    path('<int:pk>/items/<int:item_pk>/eliminar/', views.item_plantilla_eliminar, name='item_plantilla_eliminar'),
    path('<int:pk>/consumo/', views.registrar_consumo, name='registrar_consumo'),
    path('<int:pk>/reponer/', views.reponer_carro, name='reponer_carro'),
]
