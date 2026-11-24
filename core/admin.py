"""
Registro de modelos Core en el admin de Django.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    SeccionCurso, Usuario, Paciente, MedicoPrescriptor, AuditoriaInmutable, AlertaSistema, EscenarioSimulacion
)


@admin.register(SeccionCurso)
class SeccionCursoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion', 'activa', 'fecha_creacion')
    list_filter = ('activa',)
    search_fields = ('nombre', 'descripcion')


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'rut', 'get_full_name', 'seccion', 'rol', 'is_active')
    list_filter = ('rol', 'seccion', 'is_active')
    search_fields = ('username', 'rut', 'first_name', 'last_name', 'seccion')
    fieldsets = UserAdmin.fieldsets + (
        ('Datos CESFAM', {
            'fields': ('rut', 'rol', 'seccion', 'telefono', 'activo_sistema', 'pin_seguridad')
        }),
    )


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('rut', 'apellido_paterno', 'apellido_materno', 'nombres', 'prevision', 'cronico', 'activo')
    list_filter = ('prevision', 'cronico', 'activo')
    search_fields = ('rut', 'nombres', 'apellido_paterno', 'apellido_materno')


@admin.register(MedicoPrescriptor)
class MedicoPrescriptorAdmin(admin.ModelAdmin):
    list_display = ('rut', 'apellido_paterno', 'nombres', 'especialidad', 'registro_sis', 'habilitado')
    list_filter = ('habilitado', 'especialidad')
    search_fields = ('rut', 'nombres', 'apellido_paterno', 'registro_sis')


@admin.register(AuditoriaInmutable)
class AuditoriaInmutableAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'usuario_username', 'rol', 'accion', 'entidad_afectada', 'ip_origen')
    list_filter = ('rol', 'accion')
    search_fields = ('usuario_username', 'accion', 'entidad_afectada')
    readonly_fields = ('timestamp', 'ip_origen', 'usuario', 'usuario_username', 'rol', 'accion', 'entidad_afectada', 'valores_anteriores', 'valores_nuevos')


@admin.register(AlertaSistema)
class AlertaSistemaAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'nivel', 'tipo', 'medicamento', 'lote', 'dias_restantes', 'leida')
    list_filter = ('nivel', 'tipo', 'leida')
    search_fields = ('medicamento', 'lote')


@admin.register(EscenarioSimulacion)
class EscenarioSimulacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'modalidad', 'activo', 'mostrar_consigna_a_estudiantes', 'creado_por', 'fecha_creacion')
    list_filter = ('activo', 'modalidad', 'mostrar_consigna_a_estudiantes')
    search_fields = ('nombre', 'descripcion', 'consignas_personalizadas')
    filter_horizontal = ('pacientes', 'recetas')
