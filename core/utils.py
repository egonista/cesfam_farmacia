"""
Utilidades comunes del sistema CESFAM Farmacia.
Incluye: Validación de RUT chileno, cifrado Fernet, helpers varios.
"""
import base64
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet


# ============================================================
# VALIDACIÓN DE RUT CHILENO (Módulo 11)
# ============================================================

def limpiar_rut(rut: str) -> str:
    """Limpia un RUT eliminando puntos, guiones y espacios."""
    return re.sub(r'[.\-\s]', '', rut).upper()


def calcular_digito_verificador(cuerpo: str) -> str:
    """
    Calcula el dígito verificador de un RUT chileno usando el Módulo 11.
    
    Algoritmo:
    1. Se toma el cuerpo numérico del RUT (sin dígito verificador).
    2. Se multiplica cada dígito por los factores [2,3,4,5,6,7] de derecha a izquierda, cíclicamente.
    3. Se suma todo y se calcula 11 - (suma mod 11).
    4. Si el resultado es 11 -> '0', si es 10 -> 'K', de lo contrario el dígito.
    """
    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2
    resto = 11 - (suma % 11)
    if resto == 11:
        return '0'
    elif resto == 10:
        return 'K'
    return str(resto)


def validar_rut(rut: str) -> bool:
    """
    Valida un RUT chileno completo (con dígito verificador).
    Acepta formatos: '12345678-9', '12.345.678-9', '123456789'.
    Retorna True si el RUT es válido.
    """
    if not rut:
        return False
    
    rut_limpio = limpiar_rut(rut)
    
    if len(rut_limpio) < 2:
        return False
    
    cuerpo = rut_limpio[:-1]
    dv_ingresado = rut_limpio[-1]
    
    if not cuerpo.isdigit():
        return False
    
    if len(cuerpo) < 7 or len(cuerpo) > 8:
        return False
    
    dv_calculado = calcular_digito_verificador(cuerpo)
    return dv_ingresado == dv_calculado


def formatear_rut(rut: str) -> str:
    """Formatea un RUT limpio al formato XX.XXX.XXX-X."""
    rut_limpio = limpiar_rut(rut)
    if len(rut_limpio) < 2:
        return rut
    cuerpo = rut_limpio[:-1]
    dv = rut_limpio[-1]
    # Formatear con puntos
    cuerpo_formateado = ''
    for i, c in enumerate(reversed(cuerpo)):
        if i > 0 and i % 3 == 0:
            cuerpo_formateado = '.' + cuerpo_formateado
        cuerpo_formateado = c + cuerpo_formateado
    return f'{cuerpo_formateado}-{dv}'


# ============================================================
# CIFRADO SIMÉTRICO (Fernet / AES) - Ley N° 21.719
# ============================================================

def generar_clave_fernet() -> bytes:
    """Genera una nueva clave Fernet (base64)."""
    return Fernet.generate_key()


def cifrar_dato(dato: str, clave: bytes = None) -> str:
    """
    Cifra un dato sensible usando Fernet (AES-128-CBC).
    Cumple con Ley N° 21.719 de protección de datos personales.
    """
    if clave is None:
        from django.conf import settings
        clave = settings.FERNET_KEY.encode() if isinstance(settings.FERNET_KEY, str) else settings.FERNET_KEY
    f = Fernet(clave)
    return f.encrypt(dato.encode()).decode()


def descifrar_dato(dato_cifrado: str, clave: bytes = None) -> str:
    """
    Descifra un dato protegido con Fernet.
    """
    if clave is None:
        from django.conf import settings
        clave = settings.FERNET_KEY.encode() if isinstance(settings.FERNET_KEY, str) else settings.FERNET_KEY
    f = Fernet(clave)
    return f.decrypt(dato_cifrado.encode()).decode()


# ============================================================
# AUDITORÍA INMUTABLE (PostgreSQL JSONB + Respaldo Opcional)
# ============================================================

def registrar_auditoria(usuario, accion, entidad, valores_anteriores=None, valores_nuevos=None, ip='127.0.0.1'):
    """
    Registra un evento de auditoría inmutable en PostgreSQL (tabla core_auditoriainmutable con JSONB).
    Patrón append-only: los registros nunca se modifican ni eliminan.
    """
    user_obj = usuario if hasattr(usuario, 'id') and getattr(usuario, 'id', None) else None
    username_str = getattr(usuario, 'username', str(usuario))
    rol_str = getattr(usuario, 'rol', 'sistema')

    # 1. Registro primario en PostgreSQL (JSONB)
    try:
        from core.models import AuditoriaInmutable
        AuditoriaInmutable.objects.create(
            ip_origen=ip,
            usuario=user_obj,
            usuario_username=username_str,
            rol=rol_str,
            accion=accion,
            entidad_afectada=entidad,
            valores_anteriores=valores_anteriores or {},
            valores_nuevos=valores_nuevos or {},
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'Error registrando auditoría PostgreSQL: {e}')

    # 2. Sincronización secundaria opcional (si se habilita modo híbrido)
    try:
        from core.mongo_client import get_mongo_db
        db = get_mongo_db()
        if db is not None:
            db.auditoria_inmutable.insert_one({
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'ip_origen': ip,
                'usuario_id': user_obj.id if user_obj else 0,
                'usuario_username': username_str,
                'rol': rol_str,
                'accion': accion,
                'entidad_afectada': entidad,
                'valores_anteriores': valores_anteriores or {},
                'valores_nuevos': valores_nuevos or {},
            })
    except Exception:
        pass


# ============================================================
# HELPERS DE FECHA
# ============================================================

def dias_hasta_vencimiento(fecha_vencimiento):
    """Calcula los días restantes hasta la fecha de vencimiento."""
    from datetime import date
    if isinstance(fecha_vencimiento, datetime):
        fecha_vencimiento = fecha_vencimiento.date()
    return (fecha_vencimiento - date.today()).days


# ============================================================
# HELPERS DE ESCENARIOS DE SIMULACIÓN Y ROL EFECTIVO
# ============================================================

def obtener_rol_efectivo(request):
    """
    Retorna el rol efectivo de la sesión activa (considerando /simular-rol/
    y el rol autenticado en request.user).
    """
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return None
    rol_sesion = request.session.get('rol_simulado')
    if rol_sesion in ('admin', 'quimico', 'tecnico', 'clinico') and rol_sesion == request.user.rol:
        return rol_sesion
    return getattr(request.user, 'rol', None)


def obtener_filtro_escenario(request):
    """
    Determina el escenario activo y si la vista actual debe filtrar por él:
    - Técnico y Q.F.: filtran estrictamente por el escenario activo (si existe).
    - Administrador: filtra por el escenario activo por defecto ('escenario')
      para visualizar cambios al instante, o muestra todo si pasa ?vista=completo.
    Retorna tupla: (escenario_activo, filtrar_por_escenario, vista_actual).
    """
    from core.models import EscenarioSimulacion

    escenario_activo = EscenarioSimulacion.obtener_activo()
    rol = obtener_rol_efectivo(request)

    if escenario_activo is None:
        return None, False, 'completo'

    if rol == 'admin':
        vista = request.GET.get('vista', 'escenario').strip()
        if vista == 'completo':
            return escenario_activo, False, 'completo'
        return escenario_activo, True, 'escenario'

    if rol in ('tecnico', 'quimico'):
        return escenario_activo, True, 'escenario'

    return escenario_activo, False, 'escenario'


def generar_rut_unico_paciente():
    """Genera un RUT chileno válido (Módulo 11) que no exista aún en Paciente."""
    import random
    from core.models import Paciente

    for _ in range(100):
        cuerpo = str(random.randint(15000000, 24999999))
        dv = calcular_digito_verificador(cuerpo)
        rut_fmt = formatear_rut(f'{cuerpo}{dv}')
        if not Paciente.objects.filter(rut=rut_fmt).exists():
            return rut_fmt
    raise RuntimeError('No fue posible generar un RUT chileno único.')
