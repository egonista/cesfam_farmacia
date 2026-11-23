"""
URLs del módulo GES/AUGE del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'ges'

urlpatterns = [
    path('inscripciones/', views.inscripcion_list, name='inscripcion_list'),
    path('inscripciones/<int:pk>/', views.inscripcion_detalle, name='inscripcion_detalle'),
    path('verificar/<int:paciente_pk>/', views.verificar_ges, name='verificar_ges'),
]
