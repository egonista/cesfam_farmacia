"""
Vistas oficiales de manejo de errores HTTP (400, 403, 404, 500) y fallos CSRF
para CESFAM Farmacia Asistencial — INACAP.
Sin trazas técnicas ni exposición de datos sensibles.
"""
from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import loader


def error_400(request, exception=None):
    """HTTP 400 Bad Request personalizado."""
    return render(request, '400.html', {
        'ruta_intentada': getattr(request, 'path', ''),
    }, status=400)


def error_403(request, exception=None):
    """HTTP 403 Forbidden personalizado (unificado con Acceso Denegado RBAC)."""
    return render(request, '403.html', {
        'ruta_intentada': getattr(request, 'path', ''),
    }, status=403)


def error_404(request, exception=None):
    """HTTP 404 Not Found personalizado."""
    return render(request, '404.html', {
        'ruta_intentada': getattr(request, 'path', ''),
    }, status=404)


def error_500(request):
    """
    HTTP 500 Internal Server Error completamente autocontenido.
    No ejecuta queries a base de datos ni context processors para no fallar en cascada.
    """
    try:
        template = loader.get_template('500.html')
        html = template.render({}, None)
    except Exception:
        html = (
            '<!DOCTYPE html><html lang="es-CL"><head><meta charset="UTF-8">'
            '<title>500 | CESFAM Farmacia Asistencial - INACAP</title></head>'
            '<body style="font-family:sans-serif;text-align:center;padding:3rem;background:#F8FAFC;color:#0F172A;">'
            '<h1 style="color:#C8102E;font-size:3rem;margin:0;">500</h1>'
            '<h2>Error interno del servidor</h2>'
            '<p>Ocurrió un inconveniente inesperado. Por favor vuelve al inicio e inténtalo nuevamente.</p>'
            '<a href="/" style="display:inline-block;padding:10px 20px;background:#C8102E;color:#fff;'
            'text-decoration:none;border-radius:8px;font-weight:bold;">&larr; Volver al Dashboard</a>'
            '</body></html>'
        )
    return HttpResponseServerError(html)


def csrf_failure(request, reason=''):
    """Vista limpia para fallos de verificación CSRF (sin exponer detalles internos)."""
    return render(request, '403_csrf.html', {
        'ruta_intentada': getattr(request, 'path', ''),
    }, status=403)


def preview_error(request, codigo):
    """
    Vista de demostración en vivo (/errores/<codigo>/) para probar 400, 403, 404, 500 y csrf
    con sus códigos HTTP reales incluso con DEBUG = True.
    """
    codigo_norm = str(codigo or '').strip().lower()
    if codigo_norm == '400':
        return error_400(request)
    if codigo_norm == '403':
        return error_403(request)
    if codigo_norm == '404':
        return error_404(request)
    if codigo_norm == '500':
        sin_sesion = True
        try:
            sin_sesion = not (hasattr(request, 'user') and request.user.is_authenticated)
        except Exception:
            sin_sesion = True
        template = loader.get_template('500.html')
        return HttpResponseServerError(template.render({'sin_sesion': sin_sesion}, None))
    if codigo_norm == 'csrf':
        return csrf_failure(request)
    return error_404(request)
