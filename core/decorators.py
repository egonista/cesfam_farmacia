"""
Decoradores y guardias de Control de Acceso Basado en Roles (RBAC) en Backend.
Valida siempre el rol desde la sesión autenticada en el servidor (request.user.rol)
y responde con HTTP 403 Forbidden + plantilla de Acceso Denegado o JSON 403.
"""
from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import render

from core.utils import registrar_auditoria


def denegar_acceso(request, motivo='Su perfil de usuario no tiene permisos para acceder a esta sección o ejecutar esta operación.', roles_autorizados=None):
    """
    Registra el intento bloqueado en la bitácora de auditoría inmutable y
    devuelve HTTP 403 Forbidden (HTML o JSON según el endpoint).
    """
    if request.user.is_authenticated:
        try:
            registrar_auditoria(
                request.user,
                'Acceso Denegado por Control de Rol (403)',
                f'{request.method} {request.path}',
                valores_nuevos={
                    'rol_actual': request.user.rol,
                    'motivo': motivo,
                    'roles_autorizados': list(roles_autorizados) if roles_autorizados else [],
                }
            )
        except Exception:
            pass

    if request.path.startswith('/api/') or request.headers.get('Accept', '').startswith('application/json'):
        return JsonResponse({
            'error': '403 Forbidden',
            'detail': motivo,
            'rol_actual': request.user.get_rol_display() if request.user.is_authenticated else 'Anónimo',
        }, status=403)

    return render(request, '403.html', {
        'motivo': motivo,
        'ruta_intentada': request.path,
        'roles_autorizados': roles_autorizados or [],
    }, status=403)


def rol_requerido(*roles_permitidos, motivo=None):
    """
    Decorador de vista que exige sesión activa y que request.user.rol
    pertenezca estrictamente a roles_permitidos.
    Si no cumple, devuelve HTTP 403 Forbidden.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            if request.user.rol not in roles_permitidos:
                msg = motivo or (
                    f'El perfil "{request.user.get_rol_display()}" no está autorizado '
                    f'para acceder a este módulo o ejecutar esta acción.'
                )
                return denegar_acceso(request, motivo=msg, roles_autorizados=roles_permitidos)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
