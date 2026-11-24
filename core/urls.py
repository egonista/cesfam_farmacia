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
    path('auditoria/respaldo-bd/', views.descargar_respaldo_bd, name='respaldo_bd'),
    path('usuarios/', views.usuario_list, name='usuario_list'),
    path('usuarios/plantilla/<str:formato>/', views.usuario_descargar_plantilla, name='usuario_descargar_plantilla'),
    path('usuarios/importar/', views.usuario_importar_curso, name='usuario_importar_curso'),
    path('usuarios/secciones/crear/', views.seccion_crear, name='seccion_crear'),
    path('usuarios/secciones/<int:pk>/editar/', views.seccion_editar, name='seccion_editar'),
    path('usuarios/secciones/<int:pk>/eliminar/', views.seccion_eliminar, name='seccion_eliminar'),
    path('reiniciar-escenario/', views.reiniciar_escenario, name='reiniciar_escenario'),
    path('admin-panel/escenarios/', views.escenario_list, name='escenario_list'),
    path('admin-panel/escenarios/crear/', views.escenario_crear, name='escenario_crear'),
    path('admin-panel/escenarios/nuevo/', views.escenario_crear, name='escenario_nuevo'),
    path('admin-panel/escenarios/<int:pk>/editar/', views.escenario_editar, name='escenario_editar'),
    path('admin-panel/escenarios/<int:pk>/activar/', views.escenario_activar, name='escenario_activar'),
    path('admin-panel/escenarios/<int:pk>/restaurar/', views.escenario_restaurar_recetas, name='escenario_restaurar_recetas'),
    path('admin-panel/escenarios/<int:pk>/duplicar/', views.escenario_duplicar, name='escenario_duplicar'),
    path('admin-panel/escenarios/<int:pk>/inyectar-caso/', views.escenario_inyectar_caso, name='escenario_inyectar_caso'),
    path('admin-panel/escenarios/<int:pk>/eliminar/', views.escenario_eliminar, name='escenario_eliminar'),
    path('admin-panel/escenarios/api/paciente/', views.api_escenario_crear_paciente, name='api_escenario_crear_paciente'),
    path('admin-panel/escenarios/api/receta/', views.api_escenario_crear_receta, name='api_escenario_crear_receta'),
    path('admin-panel/escenarios/api/caso-aleatorio/', views.api_escenario_caso_aleatorio, name='api_escenario_caso_aleatorio'),
    path('admin-panel/banco-pacientes/', views.banco_pacientes, name='banco_pacientes'),
    path('admin-panel/banco-pacientes/<int:pk>/asignar/', views.banco_paciente_asignar_escenarios, name='banco_paciente_asignar_escenarios'),
    path('api/simulacion/estado/', views.api_simulacion_estado, name='api_simulacion_estado'),
    path('api/validar-rut/', views.api_validar_rut, name='api_validar_rut'),
    path('api/health/', views.api_health, name='api_health'),
    path('api/health', views.api_health, name='api_health_no_slash'),
]
