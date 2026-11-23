"""
URLs del módulo Dispensación del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'dispensacion'

urlpatterns = [
    path('recetas/', views.receta_list, name='receta_list'),
    path('recetas/crear/', views.receta_crear, name='receta_crear'),
    path('recetas/<int:pk>/', views.receta_detalle, name='receta_detalle'),
    path('dispensar/', views.dispensar, name='dispensar'),
    path('dispensar/<int:receta_pk>/', views.dispensar_receta, name='dispensar_receta'),
    path('historial/', views.historial, name='historial'),
    path('historial/<int:pk>/', views.dispensacion_detalle, name='dispensacion_detalle'),
]
