"""
Context processors globales para inyectar datos en todos los templates.
"""
from datetime import date


def global_context(request):
    """Inyecta variables globales en todos los templates."""
    context = {
        'proyecto_nombre': 'Sistema de Gestión Farmacia CESFAM',
        'proyecto_version': '1.0.0',
        'proyecto_autores': 'Egon Muñoz Muttel & Renato Suazo Burgos',
        'proyecto_institucion': 'INACAP - Proyecto Integrado 2026',
        'anio_actual': date.today().year,
    }
    if request.user.is_authenticated:
        try:
            context['usuario_rol'] = request.user.get_rol_display()
            context['usuario_nombre_completo'] = request.user.get_full_name()
        except Exception:
            pass
    return context
