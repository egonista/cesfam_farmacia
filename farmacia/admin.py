"""
Registro de modelos Farmacia en el admin de Django.
"""
from django.contrib import admin
from .models import (
    CategoriaMedicamento, Medicamento, Ubicacion, Lote, MovimientoStock,
    OrdenAbastecimiento, DetalleOrdenAbastecimiento
)


@admin.register(CategoriaMedicamento)
class CategoriaMedicamentoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'es_controlado')
    list_filter = ('es_controlado',)
    search_fields = ('nombre',)


@admin.register(Medicamento)
class MedicamentoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre_generico', 'concentracion', 'forma_farmaceutica', 'categoria', 'stock_total', 'en_quiebre', 'es_controlado', 'activo')
    list_filter = ('categoria', 'es_controlado', 'activo', 'forma_farmaceutica')
    search_fields = ('codigo', 'nombre_generico', 'nombre_comercial')


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'activa')
    list_filter = ('tipo', 'activa')


@admin.register(Lote)
class LoteAdmin(admin.ModelAdmin):
    list_display = ('numero_lote', 'medicamento', 'ubicacion', 'cantidad_actual', 'fecha_vencimiento', 'esta_vencido', 'alerta_vencimiento', 'activo')
    list_filter = ('activo', 'ubicacion', 'medicamento__categoria')
    search_fields = ('numero_lote', 'medicamento__nombre_generico')
    date_hierarchy = 'fecha_vencimiento'


@admin.register(MovimientoStock)
class MovimientoStockAdmin(admin.ModelAdmin):
    list_display = ('lote', 'tipo', 'cantidad', 'usuario', 'fecha')
    list_filter = ('tipo', 'fecha')
    search_fields = ('lote__numero_lote', 'lote__medicamento__nombre_generico')
    date_hierarchy = 'fecha'


class DetalleOrdenInline(admin.TabularInline):
    model = DetalleOrdenAbastecimiento
    extra = 1


@admin.register(OrdenAbastecimiento)
class OrdenAbastecimientoAdmin(admin.ModelAdmin):
    list_display = ('numero_orden', 'tipo', 'estado', 'proveedor', 'solicitante', 'generada_automaticamente', 'fecha_emision')
    list_filter = ('estado', 'tipo', 'generada_automaticamente')
    search_fields = ('numero_orden', 'proveedor', 'guia_despacho')
    inlines = [DetalleOrdenInline]
