"""
Registro de modelos Controlados en el admin de Django.
"""
from django.contrib import admin
from .models import LibroControlados


@admin.register(LibroControlados)
class LibroControladosAdmin(admin.ModelAdmin):
    list_display = ('folio', 'medicamento', 'tipo_movimiento', 'cantidad', 'saldo_anterior', 'saldo_posterior', 'quimico_responsable', 'verificacion_2fa', 'fecha_registro')
    list_filter = ('tipo_movimiento', 'verificacion_2fa', 'medicamento')
    search_fields = ('folio', 'medicamento__nombre_generico', 'paciente__rut')
    readonly_fields = ('folio', 'fecha_registro')
