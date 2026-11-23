"""
URLs del módulo Reportes del Sistema CESFAM.
"""
from django.urls import path
from . import views

app_name = 'reportes'

urlpatterns = [
    path('', views.index, name='index'),
    path('exportar/pdf/', views.exportar_pdf, name='exportar_pdf'),
    path('exportar/excel/', views.exportar_excel, name='exportar_excel'),
    path('api/dashboard-data/', views.api_dashboard_data, name='api_dashboard_data'),
]
