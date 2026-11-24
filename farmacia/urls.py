"""
URLs del módulo Farmacia del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'farmacia'

urlpatterns = [
    path('medicamentos/', views.medicamento_list, name='medicamento_list'),
    path('arsenal/', views.medicamento_list, name='arsenal'),
    path('medicamentos/<int:pk>/', views.medicamento_detalle, name='medicamento_detalle'),
    path('lotes/', views.lote_list, name='lote_list'),
    path('lotes/crear/', views.lote_crear, name='lote_crear'),
    path('lotes/<int:pk>/cuarentena/', views.lote_cuarentena, name='lote_cuarentena'),
    path('movimientos/', views.movimiento_list, name='movimiento_list'),
    path('movimientos/traspaso/', views.traspaso, name='traspaso'),
    path('alertas/vencimiento/', views.alertas_vencimiento, name='alertas_vencimiento'),
    path('abastecimiento/', views.orden_list, name='orden_list'),
    path('abastecimiento/generar-automatica/', views.generar_orden_automatica, name='generar_orden_automatica'),
    path('abastecimiento/<int:pk>/', views.orden_detalle, name='orden_detalle'),
]
