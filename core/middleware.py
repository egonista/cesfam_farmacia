"""
Middleware de seguridad y auditoría para CESFAM Farmacia.
"""
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """Middleware que añade cabeceras de seguridad HTTP (CSP, X-Content-Type-Options, etc.)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        return response


class AuditMiddleware:
    """Middleware que registra acciones de escritura (POST/PUT/DELETE) en la auditoría de PostgreSQL."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Solo auditar métodos de escritura válidos (los 403/errores de permisos ya los audita denegar_acceso)
        if request.method in ('POST', 'PUT', 'DELETE') and request.user.is_authenticated and response.status_code < 400:
            try:
                from core.models import AuditoriaInmutable
                entidad = request.path.strip('/').split('/')[0] if request.path.strip('/') else 'dashboard'
                AuditoriaInmutable.objects.create(
                    ip_origen=self._get_client_ip(request),
                    usuario=request.user,
                    usuario_username=request.user.username,
                    rol=getattr(request.user, 'rol', 'desconocido'),
                    accion=f'{request.method} {request.path}',
                    entidad_afectada=entidad,
                    valores_anteriores={},
                    valores_nuevos={'ruta': request.path, 'metodo': request.method},
                )
            except Exception as e:
                logger.warning(f'Error al registrar auditoría middleware: {e}')
        return response

    @staticmethod
    def _get_client_ip(request):
        """Obtiene la IP del cliente desde el request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '127.0.0.1')


class CustomErrorPagesMiddleware:
    """
    En modo local (DEBUG = True), intercepta respuestas HTML 404 técnicas de Django
    (excluyendo /api/, /static/ y /media/) para mostrar la plantilla institucional 404.html
    sin necesidad de desactivar DEBUG durante demostraciones en vivo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 404:
            from django.conf import settings
            path = request.path or ''
            accept = request.headers.get('Accept', '')
            es_recurso_excluido = (
                path.startswith('/api/')
                or path.startswith('/static/')
                or path.startswith('/media/')
                or accept.startswith('application/json')
            )
            if getattr(settings, 'DEBUG', False) and not es_recurso_excluido:
                content_type = response.get('Content-Type', '')
                # Solo reemplazar si es la página técnica amarilla de Django (no nuestra 404 ya renderizada)
                if 'text/html' in content_type and b'Farmacia Asistencial CESFAM' not in getattr(response, 'content', b''):
                    from core.error_views import error_404
                    return error_404(request)
        return response
