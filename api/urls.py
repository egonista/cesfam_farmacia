"""
URLs de la API REST del Sistema CESFAM Farmacia.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'api'

router = DefaultRouter()
router.register(r'medicamentos', views.MedicamentoViewSet, basename='medicamento')
router.register(r'lotes', views.LoteViewSet, basename='lote')
router.register(r'pacientes', views.PacienteViewSet, basename='paciente')
router.register(r'recetas', views.RecetaViewSet, basename='receta')
router.register(r'dispensaciones', views.DispensacionViewSet, basename='dispensacion')

urlpatterns = [
    path('', include(router.urls)),
]
