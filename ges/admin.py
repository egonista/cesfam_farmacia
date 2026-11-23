"""
Registro de modelos GES en el admin de Django.
"""
from django.contrib import admin
from .models import PatologiaGES, CanastaGES, InscripcionGES, CuotaGES


class CanastaGESInline(admin.TabularInline):
    model = CanastaGES
    extra = 1


@admin.register(PatologiaGES)
class PatologiaGESAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activa')
    list_filter = ('activa',)
    search_fields = ('codigo', 'nombre')
    inlines = [CanastaGESInline]


@admin.register(InscripcionGES)
class InscripcionGESAdmin(admin.ModelAdmin):
    list_display = ('paciente', 'patologia', 'fecha_inscripcion', 'activa')
    list_filter = ('activa', 'patologia')
    search_fields = ('paciente__rut', 'paciente__apellido_paterno')


@admin.register(CuotaGES)
class CuotaGESAdmin(admin.ModelAdmin):
    list_display = ('inscripcion', 'canasta', 'numero_cuota', 'cantidad_entregada', 'fecha_entrega')
    list_filter = ('canasta__patologia',)
