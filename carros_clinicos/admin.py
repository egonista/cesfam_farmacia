"""
Registro de modelos Carros Clínicos en el admin de Django.
"""
from django.contrib import admin
from .models import CarroClinico, PlantillaItemCarro, ConsumoCarroClinico, ReposicionCarro


class PlantillaItemCarroInline(admin.TabularInline):
    model = PlantillaItemCarro
    extra = 1


@admin.register(CarroClinico)
class CarroClinicoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'tipo', 'estado', 'ubicacion_fisica', 'numero_precinto', 'activo')
    list_filter = ('tipo', 'estado', 'activo')
    search_fields = ('nombre', 'ubicacion_fisica')
    inlines = [PlantillaItemCarroInline]


@admin.register(ConsumoCarroClinico)
class ConsumoCarroClinicoAdmin(admin.ModelAdmin):
    list_display = ('carro', 'item', 'cantidad_consumida', 'personal_clinico', 'fecha')
    list_filter = ('carro', 'fecha')
    date_hierarchy = 'fecha'


@admin.register(ReposicionCarro)
class ReposicionCarroAdmin(admin.ModelAdmin):
    list_display = ('carro', 'item', 'cantidad_repuesta', 'lote', 'usuario_farmacia', 'nuevo_precinto', 'fecha')
    list_filter = ('carro', 'fecha')
    date_hierarchy = 'fecha'
