"""
Context processors globales para inyectar datos en todos los templates.
"""
from datetime import date
from django.conf import settings


def global_context(request):
    """Inyecta variables globales en todos los templates."""
    modo_sim = getattr(settings, 'MODO_SIMULACION_DOCENTE', False)
    modo_presentacion = bool(getattr(settings, 'DEBUG', False) or modo_sim)
    context = {
        'proyecto_nombre': 'Sistema de Gestión Farmacia CESFAM',
        'proyecto_version': '1.0.0',
        'proyecto_autores': 'Egon Muñoz Muttel & Renato Suazo Burgos',
        'proyecto_institucion': 'INACAP - Proyecto Integrado 2026',
        'anio_actual': date.today().year,
        'modo_simulacion_docente': modo_sim,
    }
    if request.user.is_authenticated:
        try:
            from core.models import EscenarioSimulacion
            esc_act = EscenarioSimulacion.obtener_activo()
            context['escenario_activo'] = esc_act
            context['escenario_version'] = (
                esc_act.actualizado_en.isoformat() if esc_act and esc_act.actualizado_en else 'none'
            )
        except Exception:
            context['escenario_activo'] = None
            context['escenario_version'] = 'none'
        try:
            context['usuario_rol'] = request.user.get_rol_display()
            context['usuario_nombre_completo'] = request.user.get_full_name()
            if modo_presentacion:
                context['mostrar_cambio_rapido'] = True
            else:
                context['mostrar_cambio_rapido'] = bool(
                    request.user.rol == 'admin' or request.session.get('is_real_admin') is True
                )
        except Exception:
            context['mostrar_cambio_rapido'] = modo_presentacion
    else:
        context['escenario_activo'] = None
        context['escenario_version'] = 'none'
        context['mostrar_cambio_rapido'] = False
    return context
