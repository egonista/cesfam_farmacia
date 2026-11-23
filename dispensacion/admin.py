"""
Registro de modelos Dispensación en el admin de Django.
"""
from django.contrib import admin
from .models import Receta, DetalleReceta, TerceroAutorizado, Dispensacion, DetalleDispensacion


class DetalleRecetaInline(admin.TabularInline):
    model = DetalleReceta
    extra = 1


class DetalleDispensacionInline(admin.TabularInline):
    model = DetalleDispensacion
    extra = 0


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    list_display = ('numero_receta', 'paciente', 'medico', 'tipo', 'estado', 'fecha_emision', 'esta_vigente')
    list_filter = ('estado', 'tipo', 'fecha_emision')
    search_fields = ('numero_receta', 'paciente__rut', 'paciente__apellido_paterno')
    inlines = [DetalleRecetaInline]
    date_hierarchy = 'fecha_emision'


@admin.register(TerceroAutorizado)
class TerceroAutorizadoAdmin(admin.ModelAdmin):
    list_display = ('rut', 'nombres', 'apellido_paterno', 'parentesco', 'telefono')
    search_fields = ('rut', 'nombres', 'apellido_paterno')


@admin.register(Dispensacion)
class DispensacionAdmin(admin.ModelAdmin):
    list_display = ('id', 'receta', 'usuario_dispensador', 'retiro_tercero', 'copago', 'fecha')
    list_filter = ('retiro_tercero', 'fecha')
    inlines = [DetalleDispensacionInline]
    date_hierarchy = 'fecha'
