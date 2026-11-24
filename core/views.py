"""
Vistas del módulo Core del Sistema CESFAM Farmacia.
Dashboard, autenticación, gestión de pacientes.
"""
import json
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import transaction
from django.db.models import Count, Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Paciente, MedicoPrescriptor, Usuario, AuditoriaInmutable, AlertaSistema, EscenarioSimulacion
)
from .utils import (
    validar_rut,
    formatear_rut,
    registrar_auditoria,
    obtener_rol_efectivo,
    obtener_filtro_escenario,
    generar_rut_unico_paciente,
)
from .decorators import rol_requerido, denegar_acceso
from farmacia.models import Medicamento, Lote
from dispensacion.models import Dispensacion, Receta
from carros_clinicos.models import CarroClinico


def login_view(request):
    """Vista de inicio de sesión (acepta username o correo institucional)."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=identificador, password=password)
        if user is None and '@' in identificador:
            u_obj = Usuario.objects.filter(email__iexact=identificador).first()
            if u_obj:
                user = authenticate(request, username=u_obj.username, password=password)
        if user is not None:
            login(request, user)
            request.session['rol_simulado'] = user.rol
            if user.rol == Usuario.Rol.ADMINISTRADOR:
                request.session['is_real_admin'] = True
                request.session['original_admin_id'] = user.pk
            else:
                request.session['is_real_admin'] = False
                request.session.pop('original_admin_id', None)
            registrar_auditoria(
                user,
                'Inicio de Sesión Exitoso',
                f'Sesión RBAC ({user.get_rol_display()})',
                valores_nuevos={'username': user.username, 'rol': user.rol}
            )
            messages.success(request, f'¡Bienvenido/a, {user.get_full_name()} ({user.get_rol_display()})!')
            return redirect('core:dashboard')
        else:
            messages.error(request, 'Credenciales inválidas. Verifique usuario y contraseña.')

    return render(request, 'registration/login.html')


def simular_rol(request, rol_key):
    """
    Selector rápido de 1-Clic para alternar entre los 4 perfiles sanitarios durante la simulación.
    Cuando MODO_SIMULACION_DOCENTE=True, permite cambiar libremente desde /login/ y desde la barra superior.
    Cuando MODO_SIMULACION_DOCENTE=False, exige que el usuario real autenticado sea Administrador (403 en otro caso).
    """
    modo_libre = getattr(settings, 'MODO_SIMULACION_DOCENTE', True)
    if not modo_libre:
        if not request.user.is_authenticated:
            return redirect('core:login')
        es_admin_real = bool(
            request.user.rol == Usuario.Rol.ADMINISTRADOR
            or request.session.get('is_real_admin') is True
        )
        if not es_admin_real:
            return denegar_acceso(
                request,
                motivo='Solo el Administrador (Docente / Coordinador del simulador) está autorizado para utilizar el selector de cambio rápido de rol.',
                roles_autorizados=('admin',)
            )

    orig_admin_id = request.session.get('original_admin_id')
    era_admin = (
        request.session.get('is_real_admin') is True
        or (request.user.is_authenticated and request.user.rol == Usuario.Rol.ADMINISTRADOR)
    )

    mapa_roles = {
        'admin': 'admin',
        'quimico': 'qf_suazo',
        'tecnico': 'tecnico_alvarez',
        'clinico': 'enfermera_gonzalez',
    }
    username = mapa_roles.get(rol_key)
    if username:
        user = Usuario.objects.filter(username=username).first()
        if user:
            login(request, user)
            request.session['rol_simulado'] = user.rol
            if modo_libre or era_admin:
                request.session['is_real_admin'] = True
                if orig_admin_id:
                    request.session['original_admin_id'] = orig_admin_id
            messages.info(
                request,
                f'Vista de simulación activa: {user.get_full_name()} — Perfil: {user.get_rol_display()}'
            )
    return redirect('core:dashboard')


def logout_view(request):
    """Cierra la sesión del usuario."""
    if request.method == 'POST':
        logout(request)
        messages.info(request, 'Sesión cerrada correctamente.')
    return redirect('core:login')


def _clasificar_evento_auditoria(accion_texto):
    """Clasifica un evento de bitácora en bloqueo 403, operación exitosa o acción válida."""
    texto = (accion_texto or '').lower()
    if '403' in texto or 'acceso denegado' in texto or 'intento bloqueado' in texto:
        return 'bloqueo', '403 Bloqueado'
    if any(k in texto for k in (
        'dispensación', 'autorización', 'visación', 'recepción',
        'reposición', 'ingreso', 'asiento', 'consumo', 'registro'
    )):
        return 'exito', 'Operación OK'
    return 'valida', 'Acción Válida'


def _construir_actividad_supervision(limite=6):
    """
    Combina operaciones operativas recientes exitosas y bloqueos 403 deduplicados,
    evitando que un mismo error repetido ocupe toda la vista del dashboard.
    """
    recientes = list(
        AuditoriaInmutable.objects.exclude(
            Q(accion__icontains='Cambio Rápido de Rol') |
            Q(accion__startswith='POST ') |
            Q(accion__startswith='PUT ') |
            Q(accion__startswith='DELETE ')
        ).order_by('-timestamp')[:100]
    )

    operaciones = []
    operaciones_keys = set()
    logins = []
    bloqueos = []
    bloqueos_por_key = {}

    for aud in recientes:
        categoria, badge_label = _clasificar_evento_auditoria(aud.accion)
        clave = (aud.usuario_username, aud.accion, aud.entidad_afectada)

        if categoria == 'bloqueo':
            if clave in bloqueos_por_key:
                bloqueos_por_key[clave]['repeticiones'] += 1
            elif len(bloqueos) < 2:
                entrada = {
                    'aud': aud,
                    'categoria': categoria,
                    'badge_label': badge_label,
                    'repeticiones': 1,
                }
                bloqueos_por_key[clave] = entrada
                bloqueos.append(entrada)
        else:
            if clave in operaciones_keys:
                continue
            operaciones_keys.add(clave)
            entrada = {
                'aud': aud,
                'categoria': categoria,
                'badge_label': badge_label,
                'repeticiones': 1,
            }
            if 'inicio de sesión' in (aud.accion or '').lower():
                logins.append(entrada)
            else:
                operaciones.append(entrada)

    cupo_exitosas = limite - len(bloqueos)
    seleccionadas = operaciones[:cupo_exitosas]
    if len(seleccionadas) < cupo_exitosas:
        faltan = cupo_exitosas - len(seleccionadas)
        seleccionadas.extend(logins[:faltan])

    combinadas = seleccionadas + bloqueos
    combinadas.sort(key=lambda item: item['aud'].timestamp, reverse=True)
    return combinadas[:limite]


@login_required
def dashboard(request):
    """Dashboard principal con KPIs en tiempo real."""
    hoy = date.today()
    hace_30 = hoy + timedelta(days=30)
    hace_60 = hoy + timedelta(days=60)
    hace_90 = hoy + timedelta(days=90)
    hace_7_dias = hoy - timedelta(days=7)

    # KPIs principales
    total_medicamentos = Medicamento.objects.filter(activo=True).count()
    medicamentos_en_quiebre = sum(
        1 for m in Medicamento.objects.filter(activo=True) if m.en_quiebre
    )

    lotes_vencidos = Lote.objects.filter(
        activo=True, en_cuarentena=False, fecha_vencimiento__lte=hoy
    ).count()
    lotes_por_vencer_30 = Lote.objects.filter(
        activo=True, en_cuarentena=False, fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hace_30
    ).count()
    lotes_por_vencer_60 = Lote.objects.filter(
        activo=True, en_cuarentena=False, fecha_vencimiento__gt=hace_30, fecha_vencimiento__lte=hace_60
    ).count()
    lotes_por_vencer_90 = Lote.objects.filter(
        activo=True, en_cuarentena=False, fecha_vencimiento__gt=hace_60, fecha_vencimiento__lte=hace_90
    ).count()

    escenario_activo, filtrar_escenario, _ = obtener_filtro_escenario(request)

    recetas_qs = Receta.objects.all()
    dispensaciones_qs = Dispensacion.objects.all()
    pacientes_qs = Paciente.objects.filter(activo=True)
    if filtrar_escenario and escenario_activo is not None:
        recetas_ids_esc = escenario_activo.recetas.values_list('id', flat=True)
        pacientes_ids_esc = escenario_activo.pacientes.values_list('id', flat=True)
        recetas_qs = recetas_qs.filter(id__in=recetas_ids_esc)
        dispensaciones_qs = dispensaciones_qs.filter(receta_id__in=recetas_ids_esc)
        pacientes_qs = pacientes_qs.filter(id__in=pacientes_ids_esc)

    recetas_hoy = recetas_qs.filter(fecha_emision=hoy).count()
    dispensaciones_hoy = dispensaciones_qs.filter(fecha__date=hoy).count()
    dispensaciones_semana = dispensaciones_qs.filter(fecha__date__gte=hace_7_dias).count()

    total_pacientes = pacientes_qs.count()

    # Datos para gráfico de dispensaciones últimos 7 días
    grafico_labels = []
    grafico_valores = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        grafico_labels.append(dia.strftime('%d/%m'))
        grafico_valores.append(
            dispensaciones_qs.filter(fecha__date=dia).count()
        )

    # Datos para gráfico de stock por categoría
    from farmacia.models import CategoriaMedicamento
    categorias = CategoriaMedicamento.objects.all()
    cat_labels = [c.nombre for c in categorias]
    cat_valores = [
        sum(m.stock_total for m in c.medicamentos.filter(activo=True))
        for c in categorias
    ]

    # Alertas y auditoría recientes desde PostgreSQL (JSONB)
    alertas_recientes = AlertaSistema.objects.all()[:10]
    auditoria_reciente = _construir_actividad_supervision(limite=6)
    lotes_criticos_fefo = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0, fecha_vencimiento__gt=hoy
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')[:6]
    from carros_clinicos.models import ConsumoCarroClinico
    carros_clinicos = CarroClinico.objects.filter(activo=True).prefetch_related('plantilla_items__medicamento')
    total_carros = carros_clinicos.count()
    carros_operativos = sum(
        1 for c in carros_clinicos if c.estado_efectivo == 'completo' and c.esta_completo
    )
    carros_en_reposicion = sum(
        1 for c in carros_clinicos if c.estado_efectivo == 'incompleto'
    )
    items_faltantes_carros = sum(
        1 for c in carros_clinicos for it in c.plantilla_items.all() if not it.esta_completo
    )
    mis_consumos_recientes = ConsumoCarroClinico.objects.filter(
        personal_clinico=request.user
    ).select_related('carro', 'item__medicamento').order_by('-fecha')[:8]

    context = {
        'total_medicamentos': total_medicamentos,
        'medicamentos_en_quiebre': medicamentos_en_quiebre,
        'lotes_vencidos': lotes_vencidos,
        'lotes_por_vencer_30': lotes_por_vencer_30,
        'lotes_por_vencer_60': lotes_por_vencer_60,
        'lotes_por_vencer_90': lotes_por_vencer_90,
        'recetas_hoy': recetas_hoy,
        'dispensaciones_hoy': dispensaciones_hoy,
        'dispensaciones_semana': dispensaciones_semana,
        'total_pacientes': total_pacientes,
        'grafico_labels': json.dumps(grafico_labels),
        'grafico_valores': json.dumps(grafico_valores),
        'cat_labels': json.dumps(cat_labels),
        'cat_valores': json.dumps(cat_valores),
        'alertas_recientes': alertas_recientes,
        'auditoria_reciente': auditoria_reciente,
        'lotes_criticos_fefo': lotes_criticos_fefo,
        'carros_clinicos': carros_clinicos,
        'total_carros': total_carros,
        'carros_operativos': carros_operativos,
        'carros_en_reposicion': carros_en_reposicion,
        'items_faltantes_carros': items_faltantes_carros,
        'mis_consumos_recientes': mis_consumos_recientes,
    }
    return render(request, 'core/dashboard.html', context)


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para consultar ni gestionar el padrón de pacientes.'
)
def paciente_list(request):
    """Lista de pacientes con búsqueda y su programa GES/patología activo."""
    from django.db.models import Prefetch
    from ges.models import InscripcionGES
    query = request.GET.get('q', '').strip()
    escenario_activo = EscenarioSimulacion.obtener_activo()

    pacientes = Paciente.objects.filter(activo=True).prefetch_related(
        Prefetch(
            'inscripciones_ges',
            queryset=InscripcionGES.objects.filter(activa=True).select_related('patologia'),
            to_attr='programas_ges_activos'
        ),
    )
    escenario_sin_pacientes = False
    if escenario_activo is not None:
        pacientes = pacientes.filter(
            id__in=escenario_activo.pacientes.values_list('id', flat=True)
        )
        escenario_sin_pacientes = not escenario_activo.pacientes.filter(activo=True).exists()

    if query:
        pacientes = pacientes.filter(
            Q(rut__icontains=query) |
            Q(nombres__icontains=query) |
            Q(apellido_paterno__icontains=query) |
            Q(apellido_materno__icontains=query)
        )
    return render(request, 'core/paciente_list.html', {
        'pacientes': pacientes,
        'query': query,
        'escenario_sin_pacientes': escenario_sin_pacientes,
    })


@rol_requerido(
    'admin', 'quimico',
    motivo='Solo el Administrador (Docente) o el Químico Farmacéutico pueden crear pacientes en el padrón.'
)
def paciente_crear(request):
    """Crear un nuevo paciente (Escenarios de simulación por Admin o registro en Farmacia)."""
    previsiones = Paciente.Prevision.choices
    previsiones_validas = {codigo for codigo, _ in previsiones}

    if request.method == 'POST':
        rut = request.POST.get('rut', '').strip()
        nombres = request.POST.get('nombres', '').strip()
        apellido_paterno = request.POST.get('apellido_paterno', '').strip()
        apellido_materno = request.POST.get('apellido_materno', '').strip()
        fecha_nacimiento = request.POST.get('fecha_nacimiento', '').strip()
        sexo = request.POST.get('sexo', 'M').strip()
        prevision = request.POST.get('prevision', 'fonasa_a').strip()

        tercero_nombre = request.POST.get('tercero_autorizado_nombre', '').strip()
        tercero_rut_raw = request.POST.get('tercero_autorizado_rut', '').strip()
        tercero_parentesco = request.POST.get('tercero_autorizado_parentesco', '').strip()

        def _render_error(msg):
            messages.error(request, msg)
            return render(request, 'core/paciente_form.html', {
                'datos': request.POST,
                'previsiones': previsiones,
            })

        if not all([rut, nombres, apellido_paterno, apellido_materno, fecha_nacimiento, sexo, prevision]):
            return _render_error('Completa todos los campos obligatorios marcados con asterisco (*).')

        if not validar_rut(rut):
            return _render_error('El RUT ingresado no es válido. Verifica el formato y dígito verificador (Ej: 12.345.678-9).')

        rut_formateado = formatear_rut(rut)
        if Paciente.objects.filter(rut=rut_formateado).exists():
            return _render_error(f'Ya existe un paciente registrado con el RUT {rut_formateado}.')

        if prevision not in previsiones_validas:
            return _render_error('La previsión seleccionada no corresponde a la red pública habilitada (FONASA A-D, PRAIS o Sin Previsión).')

        tercero_rut_fmt = ''
        if tercero_rut_raw:
            if not validar_rut(tercero_rut_raw):
                return _render_error('El RUT del tercero autorizado no es válido. Verifica el formato y dígito verificador.')
            tercero_rut_fmt = formatear_rut(tercero_rut_raw)

        try:
            paciente = Paciente.objects.create(
                rut=rut_formateado,
                nombres=nombres,
                apellido_paterno=apellido_paterno,
                apellido_materno=apellido_materno,
                fecha_nacimiento=fecha_nacimiento,
                sexo=sexo,
                direccion=request.POST.get('direccion', '').strip(),
                telefono=request.POST.get('telefono', '').strip(),
                email=request.POST.get('email', '').strip(),
                prevision=prevision,
                cronico=request.POST.get('cronico') == 'on',
                tercero_autorizado_nombre=tercero_nombre,
                tercero_autorizado_rut=tercero_rut_fmt,
                tercero_autorizado_parentesco=tercero_parentesco,
            )
            rol_ef = obtener_rol_efectivo(request)
            escenario_activo = EscenarioSimulacion.obtener_activo()
            incluir_en_activo = request.POST.get('incluir_en_escenario_activo') == 'on'
            if escenario_activo is not None and (rol_ef == 'quimico' or (rol_ef == 'admin' and incluir_en_activo)):
                escenario_activo.pacientes.add(paciente)
                escenario_activo.marcar_actualizado()

            registrar_auditoria(
                request.user,
                'Creación de Ficha de Paciente',
                f'Paciente {paciente.rut} ({paciente.nombre_completo})',
                valores_nuevos={
                    'rut': paciente.rut,
                    'prevision': paciente.prevision,
                    'cronico': paciente.cronico,
                    'tercero_autorizado': paciente.tercero_autorizado_nombre or None,
                }
            )
            messages.success(request, f'Paciente {paciente.nombre_completo} creado exitosamente.')
            return redirect('core:paciente_detalle', pk=paciente.pk)
        except Exception as e:
            return _render_error(f'Error al crear paciente: {e}')

    return render(request, 'core/paciente_form.html', {
        'previsiones': previsiones,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para acceder a fichas de pacientes ni historial de recetas.'
)
def paciente_detalle(request, pk):
    """Detalle de un paciente con edición de ficha, inscripción GES e historial de recetas."""
    from ges.models import PatologiaGES, InscripcionGES
    paciente = get_object_or_404(Paciente, pk=pk)

    if request.method == 'POST':
        if request.user.rol not in ('admin', 'quimico'):
            return denegar_acceso(
                request,
                motivo='Solo el Administrador o el Químico Farmacéutico pueden editar fichas de pacientes o acreditar garantías GES.',
                roles_autorizados=('admin', 'quimico')
            )
        accion = request.POST.get('accion')
        if accion == 'editar_paciente':
            previsiones_validas = {codigo for codigo, _ in Paciente.Prevision.choices}
            prevision_nueva = request.POST.get('prevision', paciente.prevision)
            tercero_rut_raw = request.POST.get('tercero_autorizado_rut', '').strip()
            if tercero_rut_raw and not validar_rut(tercero_rut_raw):
                messages.error(request, 'El RUT del tercero autorizado no es válido.')
                return redirect('core:paciente_detalle', pk=paciente.pk)
            paciente.nombres = request.POST.get('nombres', paciente.nombres).strip()
            paciente.apellido_paterno = request.POST.get('apellido_paterno', paciente.apellido_paterno).strip()
            paciente.apellido_materno = request.POST.get('apellido_materno', paciente.apellido_materno).strip()
            paciente.telefono = request.POST.get('telefono', paciente.telefono).strip()
            paciente.direccion = request.POST.get('direccion', paciente.direccion).strip()
            if prevision_nueva in previsiones_validas:
                paciente.prevision = prevision_nueva
            paciente.cronico = request.POST.get('cronico') == 'on'
            paciente.tercero_autorizado_nombre = request.POST.get('tercero_autorizado_nombre', '').strip()
            paciente.tercero_autorizado_rut = formatear_rut(tercero_rut_raw) if tercero_rut_raw else ''
            paciente.tercero_autorizado_parentesco = request.POST.get('tercero_autorizado_parentesco', '').strip()
            paciente.save()
            registrar_auditoria(
                request.user,
                'Actualización de Ficha Clínica de Paciente',
                f'Paciente {paciente.rut}',
                valores_nuevos={'nombre': paciente.nombre_completo, 'prevision': paciente.prevision, 'cronico': paciente.cronico}
            )
            messages.success(request, 'Ficha del paciente actualizada correctamente.')
            return redirect('core:paciente_detalle', pk=paciente.pk)

        elif accion == 'inscribir_ges':
            hoy = date.today()
            pat = get_object_or_404(PatologiaGES, pk=request.POST.get('patologia_id'))
            insc, created = InscripcionGES.objects.get_or_create(
                paciente=paciente,
                patologia=pat,
                defaults={
                    'fecha_inscripcion': hoy,
                    'fecha_inicio_periodo': hoy,
                    'fecha_fin_periodo': hoy + timedelta(days=365),
                    'activa': True,
                }
            )
            if not created:
                insc.activa = True
                insc.save()
            registrar_auditoria(
                request.user,
                'Acreditación de Paciente en Patología GES/AUGE',
                f'{paciente.rut} - {pat.nombre}',
                valores_nuevos={'patologia': pat.codigo, 'paciente': paciente.nombre_completo}
            )
            messages.success(request, f'Paciente acreditado en {pat.nombre} (GES/AUGE).')
            return redirect('core:paciente_detalle', pk=paciente.pk)

    recetas = paciente.recetas.all()[:20]
    inscripciones_ges = paciente.inscripciones_ges.filter(activa=True).select_related('patologia')
    patologias_ges = PatologiaGES.objects.filter(activa=True)
    return render(request, 'core/paciente_detalle.html', {
        'paciente': paciente,
        'recetas': recetas,
        'inscripciones_ges': inscripciones_ges,
        'patologias_ges': patologias_ges,
        'previsiones': Paciente.Prevision.choices,
    })


def api_validar_rut(request):
    """API endpoint para validar RUT vía AJAX (y opcionalmente verificar duplicado en pacientes)."""
    rut = request.GET.get('rut', '')
    es_valido = validar_rut(rut)
    formateado = formatear_rut(rut) if es_valido else None
    duplicado = False
    if es_valido and request.GET.get('check_paciente') == '1':
        duplicado = Paciente.objects.filter(rut=formateado).exists()
    return JsonResponse({
        'rut': rut,
        'valido': es_valido,
        'formateado': formateado,
        'duplicado': duplicado,
    })


@rol_requerido(
    'admin', 'quimico',
    motivo='La bitácora de auditoría inmutable solo puede ser consultada por el Administrador o el Químico Farmacéutico.'
)
def auditoria_list(request):
    """Visor de la Bitácora de Auditoría (Exclusivo Dirección Técnica Q.F. y Administrador)."""
    rol_filtro = request.GET.get('rol', '')
    q = request.GET.get('q', '')
    registros = AuditoriaInmutable.objects.all()
    if rol_filtro:
        registros = registros.filter(rol=rol_filtro)
    if q:
        registros = registros.filter(
            Q(accion__icontains=q) |
            Q(entidad_afectada__icontains=q) |
            Q(usuario_username__icontains=q)
        )
    return render(request, 'core/auditoria_list.html', {
        'registros': registros[:100],
        'rol_filtro': rol_filtro,
        'q': q,
        'roles': Usuario.Rol.choices,
    })


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente / Coordinador) está autorizado para gestionar usuarios y asignar roles.'
)
def usuario_list(request):
    """CRUD completo de Usuarios y Perfiles de Acceso (Exclusivo Administrador)."""
    if request.method == 'POST':
        accion_post = request.POST.get('accion_post', 'crear')
        if accion_post == 'toggle_estado':
            u_target = get_object_or_404(Usuario, pk=request.POST.get('usuario_id'))
            if u_target.pk != request.user.pk:
                estado_ant = u_target.is_active
                u_target.is_active = not u_target.is_active
                u_target.activo_sistema = u_target.is_active
                u_target.save()
                registrar_auditoria(
                    request.user,
                    'Cambio de estado de cuenta de usuario',
                    f'Usuario {u_target.username}',
                    valores_anteriores={'activo': estado_ant},
                    valores_nuevos={'activo': u_target.is_active}
                )
                messages.info(request, f'Estado de {u_target.get_full_name()} actualizado.')
            return redirect('core:usuario_list')

        elif accion_post == 'editar_usuario':
            u_target = get_object_or_404(Usuario, pk=request.POST.get('usuario_id'))
            rut_edit = request.POST.get('rut', u_target.rut).strip()
            if not validar_rut(rut_edit):
                messages.error(request, 'El RUT ingresado al editar el usuario no es válido.')
                return redirect('core:usuario_list')
            try:
                ant = {
                    'rut': u_target.rut,
                    'nombre': u_target.get_full_name(),
                    'telefono': u_target.telefono,
                    'rol': u_target.rol,
                }
                u_target.rut = formatear_rut(rut_edit)
                u_target.first_name = request.POST.get('first_name', u_target.first_name).strip()
                u_target.last_name = request.POST.get('last_name', u_target.last_name).strip()
                u_target.telefono = request.POST.get('telefono', u_target.telefono).strip()
                u_target.email = request.POST.get('email', u_target.email).strip()
                nuevo_rol = request.POST.get('rol', u_target.rol)
                if nuevo_rol in dict(Usuario.Rol.choices):
                    u_target.rol = nuevo_rol
                u_target.save()
                registrar_auditoria(
                    request.user,
                    'Edición de usuario y asignación de rol',
                    f'Usuario {u_target.username}',
                    valores_anteriores=ant,
                    valores_nuevos={
                        'rut': u_target.rut,
                        'nombre': u_target.get_full_name(),
                        'telefono': u_target.telefono,
                        'rol': u_target.rol,
                    }
                )
                messages.success(request, f'Datos y rol de {u_target.get_full_name()} actualizados.')
            except Exception as e:
                messages.error(request, f'No fue posible actualizar el usuario: {e}')
            return redirect('core:usuario_list')

        elif accion_post == 'eliminar_usuario':
            u_target = get_object_or_404(Usuario, pk=request.POST.get('usuario_id'))
            if u_target.pk != request.user.pk and u_target.username not in ('admin', 'qf_suazo', 'tecnico_alvarez', 'enfermera_gonzalez'):
                uname = u_target.username
                nombre_c = u_target.get_full_name()
                u_target.delete()
                registrar_auditoria(
                    request.user,
                    'Eliminación de cuenta de usuario',
                    f'Usuario {uname} ({nombre_c})',
                    valores_anteriores={'username': uname},
                    valores_nuevos={}
                )
                messages.warning(request, f'Usuario {nombre_c} eliminado del sistema.')
            else:
                messages.error(request, 'No se puede eliminar una cuenta base de simulación o el usuario en sesión.')
            return redirect('core:usuario_list')

        rut = request.POST.get('rut', '')
        if not validar_rut(rut):
            messages.error(request, 'El RUT ingresado no es válido.')
        else:
            try:
                nuevo_usr = Usuario.objects.create_user(
                    username=request.POST.get('username'),
                    password=request.POST.get('password', 'Inacap2026!'),
                    rut=formatear_rut(rut),
                    first_name=request.POST.get('first_name', ''),
                    last_name=request.POST.get('last_name', ''),
                    email=request.POST.get('email', ''),
                    telefono=request.POST.get('telefono', ''),
                    rol=request.POST.get('rol', 'tecnico'),
                )
                registrar_auditoria(
                    request.user,
                    'Creación de cuenta de usuario',
                    f'Usuario {nuevo_usr.username} ({nuevo_usr.get_rol_display()})',
                    valores_nuevos={
                        'username': nuevo_usr.username,
                        'rut': nuevo_usr.rut,
                        'telefono': nuevo_usr.telefono,
                        'rol': nuevo_usr.rol,
                    }
                )
                messages.success(request, f'Usuario {nuevo_usr.get_full_name()} creado correctamente.')
                return redirect('core:usuario_list')
            except Exception as e:
                messages.error(request, f'No fue posible crear el usuario: {e}')

    usuarios = Usuario.objects.all().order_by('rol', 'last_name')
    return render(request, 'core/usuario_list.html', {
        'usuarios': usuarios,
        'roles': Usuario.Rol.choices,
    })


def api_health(request):
    """Endpoint de salud asistencial (CP-04 / CP-11 del Plan de Pruebas QA)."""
    return JsonResponse({
        'status': 'HEALTHY',
        'service': 'CESFAM Farmacia Asistencial APS',
        'database': 'PostgreSQL 18 (cesfam_farmacia_db)',
        'fefo_engine': 'ACTIVE',
        'copago': 0,
    }, status=200)


@rol_requerido(
    'admin',
    motivo='Exclusivo Administrador (Docente): Solo el coordinador del simulador puede reiniciar el escenario de datos.'
)
@transaction.atomic
def reiniciar_escenario(request):
    """
    Restaura los datos base de simulación (inventario, lotes, recetas, carros y GES)
    manteniendo intactas todas las cuentas de Usuario y sus contraseñas.
    """
    if request.method != 'POST':
        return redirect('core:dashboard')

    from controlados.models import LibroControlados
    from dispensacion.models import (
        DetalleDispensacion, Dispensacion, DetalleReceta, Receta, TerceroAutorizado
    )
    from ges.models import CuotaGES, InscripcionGES, CanastaGES, PatologiaGES
    from carros_clinicos.models import (
        ConsumoCarroClinico, ReposicionCarro, PlantillaItemCarro, CarroClinico
    )
    from farmacia.models import (
        DetalleOrdenAbastecimiento, OrdenAbastecimiento, MovimientoStock,
        Lote, Medicamento, CategoriaMedicamento, Ubicacion
    )

    LibroControlados.objects.all().delete()
    DetalleDispensacion.objects.all().delete()
    CuotaGES.objects.all().delete()
    Dispensacion.objects.all().delete()
    InscripcionGES.objects.all().delete()
    CanastaGES.objects.all().delete()
    PatologiaGES.objects.all().delete()
    ConsumoCarroClinico.objects.all().delete()
    ReposicionCarro.objects.all().delete()
    PlantillaItemCarro.objects.all().delete()
    CarroClinico.objects.all().delete()
    DetalleOrdenAbastecimiento.objects.all().delete()
    OrdenAbastecimiento.objects.all().delete()
    MovimientoStock.objects.all().delete()
    DetalleReceta.objects.all().delete()
    Receta.objects.all().delete()
    TerceroAutorizado.objects.all().delete()
    Lote.objects.all().delete()
    Medicamento.objects.all().delete()
    CategoriaMedicamento.objects.all().delete()
    Ubicacion.objects.all().delete()
    Paciente.objects.all().delete()
    MedicoPrescriptor.objects.all().delete()
    AlertaSistema.objects.all().delete()
    EscenarioSimulacion.objects.all().delete()

    call_command('seed_cesfam', preservar_usuarios=True)

    registrar_auditoria(
        request.user,
        'Reinicio de Escenario de Simulación',
        'Escenario completo (Inventario, Recetas, Carros, GES)',
        valores_nuevos={'cuentas_usuario_preservadas': True},
    )
    messages.success(
        request,
        'Escenario de simulación reiniciado al estado inicial del taller. Todas las cuentas de usuarios y contraseñas se mantuvieron intactas.'
    )
    return redirect('core:dashboard')


@login_required
def api_simulacion_estado(request):
    """
    Endpoint JSON liviano para sincronización en tiempo real (sin F5)
    del escenario de simulación activo entre sesiones abiertas.
    """
    esc = (
        EscenarioSimulacion.objects.filter(activo=True)
        .only('id', 'nombre', 'actualizado_en')
        .first()
    )
    resp = JsonResponse({
        'escenario_id': esc.id if esc else None,
        'nombre': esc.nombre if esc else None,
        'version': esc.actualizado_en.isoformat() if esc and esc.actualizado_en else 'none',
    })
    resp['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return resp


def _contexto_formulario_escenario(escenario=None, form_data=None):
    """Prepara pacientes, recetas, medicamentos, médicos, GES y selecciones para el formulario de escenarios."""
    from django.db.models import Prefetch
    from ges.models import InscripcionGES, PatologiaGES

    pacientes = Paciente.objects.filter(activo=True).prefetch_related(
        Prefetch(
            'inscripciones_ges',
            queryset=InscripcionGES.objects.filter(activa=True).select_related('patologia'),
            to_attr='programas_ges_activos',
        )
    ).order_by('apellido_paterno', 'apellido_materno', 'nombres')

    recetas = (
        Receta.objects.all()
        .select_related('paciente', 'medico')
        .prefetch_related('detalles__medicamento')
        .order_by('-fecha_emision', '-id')
    )
    medicamentos_arsenal = Medicamento.objects.filter(activo=True).order_by('nombre_generico')
    medicos_habilitados = MedicoPrescriptor.objects.filter(habilitado=True).order_by('apellido_paterno')
    patologias_ges = PatologiaGES.objects.filter(activa=True).order_by('codigo')

    if form_data is not None:
        selected_pacientes_ids = {int(x) for x in form_data.getlist('pacientes') if str(x).isdigit()}
        selected_recetas_ids = {int(x) for x in form_data.getlist('recetas') if str(x).isdigit()}
        nombre_val = form_data.get('nombre', '')
        descripcion_val = form_data.get('descripcion', '')
        modalidad_val = form_data.get('modalidad', EscenarioSimulacion.Modalidad.LIBRE)
        consignas_val = form_data.get('consignas_personalizadas', '')
        mostrar_consigna_val = form_data.get('mostrar_consigna_a_estudiantes') == 'on'
        activo_val = form_data.get('activo') == 'on'
        simular_quiebre_val = form_data.get('simular_quiebre') == 'on'
        med_quiebre_raw = form_data.get('medicamento_quiebre', '')
        medicamento_quiebre_id = int(med_quiebre_raw) if str(med_quiebre_raw).isdigit() else None
        simular_alerta_fefo_val = form_data.get('simular_alerta_fefo') == 'on'
        simular_consumo_carro_val = form_data.get('simular_consumo_carro') == 'on'
    elif escenario is not None:
        selected_pacientes_ids = set(escenario.pacientes.values_list('id', flat=True))
        selected_recetas_ids = set(escenario.recetas.values_list('id', flat=True))
        nombre_val = escenario.nombre
        descripcion_val = escenario.descripcion
        modalidad_val = escenario.modalidad
        consignas_val = escenario.consignas_personalizadas
        mostrar_consigna_val = escenario.mostrar_consigna_a_estudiantes
        activo_val = escenario.activo
        simular_quiebre_val = escenario.simular_quiebre
        medicamento_quiebre_id = escenario.medicamento_quiebre_id
        simular_alerta_fefo_val = escenario.simular_alerta_fefo
        simular_consumo_carro_val = escenario.simular_consumo_carro
    else:
        selected_pacientes_ids = set()
        selected_recetas_ids = set()
        nombre_val = ''
        descripcion_val = ''
        modalidad_val = EscenarioSimulacion.Modalidad.LIBRE
        consignas_val = ''
        mostrar_consigna_val = True
        activo_val = False
        simular_quiebre_val = False
        medicamento_quiebre_id = None
        simular_alerta_fefo_val = False
        simular_consumo_carro_val = False

    return {
        'escenario': escenario,
        'modo': 'editar' if escenario is not None else 'crear',
        'pacientes': pacientes,
        'recetas': recetas,
        'medicamentos_arsenal': medicamentos_arsenal,
        'medicos_habilitados': medicos_habilitados,
        'patologias_ges': patologias_ges,
        'previsiones': Paciente.Prevision.choices,
        'tipos_receta': Receta.TipoReceta.choices,
        'modalidades': EscenarioSimulacion.Modalidad.choices,
        'selected_pacientes_ids': selected_pacientes_ids,
        'selected_recetas_ids': selected_recetas_ids,
        'nombre_val': nombre_val,
        'descripcion_val': descripcion_val,
        'modalidad_val': modalidad_val,
        'consignas_val': consignas_val,
        'mostrar_consigna_val': mostrar_consigna_val,
        'activo_val': activo_val,
        'simular_quiebre_val': simular_quiebre_val,
        'medicamento_quiebre_id': medicamento_quiebre_id,
        'simular_alerta_fefo_val': simular_alerta_fefo_val,
        'simular_consumo_carro_val': simular_consumo_carro_val,
    }


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para gestionar los Escenarios de Simulación.'
)
def escenario_list(request):
    """Listado de escenarios de simulación (evaluaciones / talleres docentes)."""
    escenarios = (
        EscenarioSimulacion.objects.select_related('creado_por', 'medicamento_quiebre')
        .annotate(
            total_pacientes=Count('pacientes', distinct=True),
            total_recetas=Count('recetas', distinct=True),
        )
        .order_by('-activo', '-fecha_creacion', 'nombre')
    )
    medicamentos_activos = Medicamento.objects.filter(activo=True).order_by('nombre_generico')
    medicos_habilitados = MedicoPrescriptor.objects.filter(habilitado=True).order_by('apellido_paterno')
    return render(request, 'core/escenario_list.html', {
        'escenarios': escenarios,
        'medicamentos_activos': medicamentos_activos,
        'medicos_habilitados': medicos_habilitados,
        'previsiones': Paciente.Prevision.choices,
        'tipos_receta': Receta.TipoReceta.choices,
    })


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para crear Escenarios de Simulación.'
)
def escenario_crear(request):
    """Crear un nuevo escenario de simulación seleccionando modalidad, consignas, pacientes y recetas."""
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        consignas_personalizadas = request.POST.get('consignas_personalizadas', '').strip()
        mostrar_consigna = request.POST.get('mostrar_consigna_a_estudiantes') == 'on'
        activar_al_guardar = request.POST.get('activo') == 'on'
        paciente_ids = [int(x) for x in request.POST.getlist('pacientes') if str(x).isdigit()]
        receta_ids = [int(x) for x in request.POST.getlist('recetas') if str(x).isdigit()]

        simular_quiebre_raw = request.POST.get('simular_quiebre') == 'on'
        simular_alerta_fefo_raw = request.POST.get('simular_alerta_fefo') == 'on'
        simular_consumo_carro_raw = request.POST.get('simular_consumo_carro') == 'on'

        modalidad_post = request.POST.get('modalidad', '').strip()
        if modalidad_post in (EscenarioSimulacion.Modalidad.LIBRE, EscenarioSimulacion.Modalidad.INCIDENCIAS):
            modalidad = modalidad_post
        elif simular_quiebre_raw or simular_alerta_fefo_raw or simular_consumo_carro_raw:
            modalidad = EscenarioSimulacion.Modalidad.INCIDENCIAS
        else:
            modalidad = EscenarioSimulacion.Modalidad.LIBRE

        es_incidencias = modalidad == EscenarioSimulacion.Modalidad.INCIDENCIAS
        simular_quiebre = simular_quiebre_raw if es_incidencias else False
        med_quiebre_raw = request.POST.get('medicamento_quiebre', '').strip()
        medicamento_quiebre = (
            Medicamento.objects.filter(pk=int(med_quiebre_raw), activo=True).first()
            if simular_quiebre and med_quiebre_raw.isdigit()
            else None
        )
        simular_alerta_fefo = simular_alerta_fefo_raw if es_incidencias else False
        simular_consumo_carro = simular_consumo_carro_raw if es_incidencias else False

        if not nombre:
            messages.error(request, 'El nombre del escenario es obligatorio.')
            return render(request, 'core/escenario_form.html', _contexto_formulario_escenario(form_data=request.POST))

        if EscenarioSimulacion.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, f'Ya existe un escenario con el nombre "{nombre}". Elige un nombre único.')
            return render(request, 'core/escenario_form.html', _contexto_formulario_escenario(form_data=request.POST))

        if simular_quiebre and medicamento_quiebre is None:
            messages.error(request, 'Selecciona un fármaco del arsenal para simular el quiebre de stock.')
            return render(request, 'core/escenario_form.html', _contexto_formulario_escenario(form_data=request.POST))

        incidencias_aplicadas = []
        with transaction.atomic():
            escenario = EscenarioSimulacion.objects.create(
                nombre=nombre,
                descripcion=descripcion,
                modalidad=modalidad,
                consignas_personalizadas=consignas_personalizadas,
                mostrar_consigna_a_estudiantes=mostrar_consigna,
                activo=False,
                creado_por=request.user,
                actualizado_en=timezone.now(),
                simular_quiebre=simular_quiebre,
                medicamento_quiebre=medicamento_quiebre,
                simular_alerta_fefo=simular_alerta_fefo,
                simular_consumo_carro=simular_consumo_carro,
            )
            escenario.pacientes.set(Paciente.objects.filter(id__in=paciente_ids))
            escenario.recetas.set(Receta.objects.filter(id__in=receta_ids))
            if activar_al_guardar:
                escenario.activar()
                incidencias_aplicadas = escenario.aplicar_incidencias(request.user)

            registrar_auditoria(
                request.user,
                'Creación de Escenario de Simulación',
                f'Escenario "{escenario.nombre}"',
                valores_nuevos={
                    'modalidad': escenario.modalidad,
                    'activo': escenario.activo,
                    'pacientes': escenario.pacientes.count(),
                    'recetas': escenario.recetas.count(),
                    'incidencias': incidencias_aplicadas,
                },
            )

        extra_inc = f' Incidencias aplicadas: {"; ".join(incidencias_aplicadas)}.' if incidencias_aplicadas else ''
        messages.success(request, f'Escenario "{escenario.nombre}" creado correctamente.{extra_inc}')
        return redirect('core:escenario_list')

    return render(request, 'core/escenario_form.html', _contexto_formulario_escenario())


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para editar Escenarios de Simulación.'
)
def escenario_editar(request, pk):
    """Editar nombre, descripción, modalidad, consignas, pacientes, recetas e incidencias de un escenario."""
    escenario = get_object_or_404(EscenarioSimulacion, pk=pk)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        consignas_personalizadas = request.POST.get('consignas_personalizadas', '').strip()
        mostrar_consigna = request.POST.get('mostrar_consigna_a_estudiantes') == 'on'
        activar_al_guardar = request.POST.get('activo') == 'on'
        paciente_ids = [int(x) for x in request.POST.getlist('pacientes') if str(x).isdigit()]
        receta_ids = [int(x) for x in request.POST.getlist('recetas') if str(x).isdigit()]

        simular_quiebre_raw = request.POST.get('simular_quiebre') == 'on'
        simular_alerta_fefo_raw = request.POST.get('simular_alerta_fefo') == 'on'
        simular_consumo_carro_raw = request.POST.get('simular_consumo_carro') == 'on'

        modalidad_post = request.POST.get('modalidad', '').strip()
        if modalidad_post in (EscenarioSimulacion.Modalidad.LIBRE, EscenarioSimulacion.Modalidad.INCIDENCIAS):
            modalidad = modalidad_post
        elif simular_quiebre_raw or simular_alerta_fefo_raw or simular_consumo_carro_raw:
            modalidad = EscenarioSimulacion.Modalidad.INCIDENCIAS
        else:
            modalidad = EscenarioSimulacion.Modalidad.LIBRE

        es_incidencias = modalidad == EscenarioSimulacion.Modalidad.INCIDENCIAS
        simular_quiebre = simular_quiebre_raw if es_incidencias else False
        med_quiebre_raw = request.POST.get('medicamento_quiebre', '').strip()
        medicamento_quiebre = (
            Medicamento.objects.filter(pk=int(med_quiebre_raw), activo=True).first()
            if simular_quiebre and med_quiebre_raw.isdigit()
            else None
        )
        simular_alerta_fefo = simular_alerta_fefo_raw if es_incidencias else False
        simular_consumo_carro = simular_consumo_carro_raw if es_incidencias else False

        if not nombre:
            messages.error(request, 'El nombre del escenario es obligatorio.')
            return render(
                request,
                'core/escenario_form.html',
                _contexto_formulario_escenario(escenario=escenario, form_data=request.POST),
            )

        if EscenarioSimulacion.objects.exclude(pk=escenario.pk).filter(nombre__iexact=nombre).exists():
            messages.error(request, f'Ya existe otro escenario con el nombre "{nombre}".')
            return render(
                request,
                'core/escenario_form.html',
                _contexto_formulario_escenario(escenario=escenario, form_data=request.POST),
            )

        if simular_quiebre and medicamento_quiebre is None:
            messages.error(request, 'Selecciona un fármaco del arsenal para simular el quiebre de stock.')
            return render(
                request,
                'core/escenario_form.html',
                _contexto_formulario_escenario(escenario=escenario, form_data=request.POST),
            )

        incidencias_aplicadas = []
        with transaction.atomic():
            era_activo = escenario.activo
            estado_anterior = {
                'nombre': escenario.nombre,
                'modalidad': escenario.modalidad,
                'activo': era_activo,
                'pacientes': escenario.pacientes.count(),
                'recetas': escenario.recetas.count(),
            }
            escenario.nombre = nombre
            escenario.descripcion = descripcion
            escenario.modalidad = modalidad
            escenario.consignas_personalizadas = consignas_personalizadas
            escenario.mostrar_consigna_a_estudiantes = mostrar_consigna
            escenario.simular_quiebre = simular_quiebre
            escenario.medicamento_quiebre = medicamento_quiebre
            escenario.simular_alerta_fefo = simular_alerta_fefo
            escenario.simular_consumo_carro = simular_consumo_carro
            escenario.actualizado_en = timezone.now()
            escenario.save(update_fields=[
                'nombre', 'descripcion', 'modalidad', 'consignas_personalizadas',
                'mostrar_consigna_a_estudiantes', 'simular_quiebre', 'medicamento_quiebre',
                'simular_alerta_fefo', 'simular_consumo_carro', 'actualizado_en'
            ])
            escenario.pacientes.set(Paciente.objects.filter(id__in=paciente_ids))
            escenario.recetas.set(Receta.objects.filter(id__in=receta_ids))

            if activar_al_guardar:
                escenario.activar()
                if not era_activo:
                    incidencias_aplicadas = escenario.aplicar_incidencias(request.user)
            elif era_activo and not activar_al_guardar:
                escenario.activo = False
                escenario.actualizado_en = timezone.now()
                escenario.save(update_fields=['activo', 'actualizado_en'])

            registrar_auditoria(
                request.user,
                'Edición de Escenario de Simulación',
                f'Escenario "{escenario.nombre}"',
                valores_anteriores=estado_anterior,
                valores_nuevos={
                    'nombre': escenario.nombre,
                    'modalidad': escenario.modalidad,
                    'activo': escenario.activo,
                    'pacientes': escenario.pacientes.count(),
                    'recetas': escenario.recetas.count(),
                    'incidencias': incidencias_aplicadas,
                },
            )

        extra_inc = f' Incidencias aplicadas: {"; ".join(incidencias_aplicadas)}.' if incidencias_aplicadas else ''
        messages.success(request, f'Escenario "{escenario.nombre}" actualizado correctamente.{extra_inc}')
        return redirect('core:escenario_list')

    return render(request, 'core/escenario_form.html', _contexto_formulario_escenario(escenario=escenario))


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para activar Escenarios de Simulación.'
)
def escenario_activar(request, pk):
    """Activa un escenario desactivando atómicamente el anterior y aplica sus incidencias."""
    if request.method != 'POST':
        return redirect('core:escenario_list')

    escenario = get_object_or_404(EscenarioSimulacion, pk=pk)
    with transaction.atomic():
        anterior = EscenarioSimulacion.obtener_activo()
        anterior_nombre = anterior.nombre if anterior else 'Ninguno'
        escenario.activar()
        incidencias_aplicadas = escenario.aplicar_incidencias(request.user)
        registrar_auditoria(
            request.user,
            'Activación de Escenario de Simulación',
            f'Escenario "{escenario.nombre}"',
            valores_anteriores={'escenario_activo': anterior_nombre},
            valores_nuevos={
                'escenario_activo': escenario.nombre,
                'incidencias_aplicadas': incidencias_aplicadas,
            },
        )

    extra_inc = f' Incidencias aplicadas: {"; ".join(incidencias_aplicadas)}.' if incidencias_aplicadas else ''
    messages.success(request, f'Escenario "{escenario.nombre}" activado para los estudiantes.{extra_inc}')
    return redirect('core:escenario_list')


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para restaurar recetas de un Escenario de Simulación.'
)
def escenario_restaurar_recetas(request, pk):
    """
    Devuelve todas las recetas vinculadas a un escenario a estado Pendiente
    (cantidad_dispensada=0 en sus ítems) sin modificar inventario, lotes ni carros clínicos.
    """
    if request.method != 'POST':
        return redirect('core:escenario_list')

    from dispensacion.models import DetalleReceta

    escenario = get_object_or_404(EscenarioSimulacion, pk=pk)
    with transaction.atomic():
        receta_ids = list(escenario.recetas.values_list('id', flat=True))
        DetalleReceta.objects.filter(receta_id__in=receta_ids).update(cantidad_dispensada=0)
        total_restauradas = Receta.objects.filter(id__in=receta_ids).update(
            estado=Receta.EstadoReceta.PENDIENTE,
            autorizada_qf=False,
            qf_autorizador=None,
            fecha_autorizacion_qf=None,
        )
        escenario.marcar_actualizado()
        registrar_auditoria(
            request.user,
            'Restauración de Recetas de Escenario',
            f'Escenario "{escenario.nombre}" ({total_restauradas} recetas)',
            valores_nuevos={'recetas_restauradas': total_restauradas, 'estado': 'pendiente', 'dispensado': 0},
        )

    messages.success(
        request,
        f'Se restauraron {total_restauradas} receta(s) del escenario "{escenario.nombre}" a estado Pendiente (dispensado = 0). El inventario, lotes y carros clínicos no fueron alterados.'
    )
    return redirect('core:escenario_list')


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para duplicar Escenarios de Simulación.'
)
def escenario_duplicar(request, pk):
    """Duplica un escenario existente (copiando configuración, pacientes y recetas) como borrador inactivo."""
    if request.method != 'POST':
        return redirect('core:escenario_list')

    origen = get_object_or_404(EscenarioSimulacion, pk=pk)
    base_nombre = f'{origen.nombre} (Copia)'
    nombre_nuevo = base_nombre
    sufijo = 2
    while EscenarioSimulacion.objects.filter(nombre__iexact=nombre_nuevo).exists():
        nombre_nuevo = f'{origen.nombre} (Copia {sufijo})'
        sufijo += 1

    with transaction.atomic():
        copia = EscenarioSimulacion.objects.create(
            nombre=nombre_nuevo[:150],
            descripcion=origen.descripcion,
            modalidad=origen.modalidad,
            consignas_personalizadas=origen.consignas_personalizadas,
            mostrar_consigna_a_estudiantes=origen.mostrar_consigna_a_estudiantes,
            activo=False,
            creado_por=request.user,
            actualizado_en=timezone.now(),
            simular_quiebre=origen.simular_quiebre,
            medicamento_quiebre=origen.medicamento_quiebre,
            simular_alerta_fefo=origen.simular_alerta_fefo,
            simular_consumo_carro=origen.simular_consumo_carro,
        )
        copia.pacientes.set(origen.pacientes.all())
        copia.recetas.set(origen.recetas.all())
        registrar_auditoria(
            request.user,
            'Duplicación de Escenario de Simulación',
            f'"{origen.nombre}" -> "{copia.nombre}"',
            valores_nuevos={
                'escenario_origen': origen.nombre,
                'escenario_copia': copia.nombre,
                'pacientes': copia.pacientes.count(),
                'recetas': copia.recetas.count(),
            },
        )

    messages.success(
        request,
        f'Escenario duplicado como "{copia.nombre}". Puedes editarlo o activarlo cuando lo necesites.'
    )
    return redirect('core:escenario_list')


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para inyectar casos rápidos en un Escenario de Simulación.'
)
def escenario_inyectar_caso(request, pk):
    """
    Inyecta en vivo un paciente nuevo + receta pendiente dentro de un escenario
    y actualiza su timestamp para que las sesiones abiertas se sincronicen solas.
    """
    if request.method != 'POST':
        return redirect('core:escenario_list')

    from dispensacion.models import DetalleReceta

    escenario = get_object_or_404(EscenarioSimulacion, pk=pk)
    nombres = request.POST.get('nombres', '').strip() or 'Valentina Sofía'
    apellido_paterno = request.POST.get('apellido_paterno', '').strip() or 'Riquelme'
    apellido_materno = request.POST.get('apellido_materno', '').strip() or 'Navarro'
    rut_raw = request.POST.get('rut', '').strip()
    prevision = request.POST.get('prevision', Paciente.Prevision.FONASA_B).strip()
    previsiones_validas = {c[0] for c in Paciente.Prevision.choices}
    if prevision not in previsiones_validas:
        prevision = Paciente.Prevision.FONASA_B

    if rut_raw:
        if not validar_rut(rut_raw):
            messages.error(request, 'El RUT ingresado para el caso rápido no es válido (Módulo 11).')
            return redirect('core:escenario_list')
        rut_fmt = formatear_rut(rut_raw)
        if Paciente.objects.filter(rut=rut_fmt).exists():
            messages.error(request, f'Ya existe un paciente registrado con el RUT {rut_fmt}. Deja el campo vacío para generar uno automático.')
            return redirect('core:escenario_list')
    else:
        rut_fmt = generar_rut_unico_paciente()

    med_id = request.POST.get('medicamento_id', '').strip()
    medicamento = (
        Medicamento.objects.filter(pk=int(med_id), activo=True).first()
        if med_id.isdigit()
        else Medicamento.objects.filter(activo=True).order_by('id').first()
    )
    if medicamento is None:
        messages.error(request, 'No hay medicamentos activos disponibles en el arsenal para inyectar la receta.')
        return redirect('core:escenario_list')

    medico_id = request.POST.get('medico_id', '').strip()
    medico = (
        MedicoPrescriptor.objects.filter(pk=int(medico_id), habilitado=True).first()
        if medico_id.isdigit()
        else MedicoPrescriptor.objects.filter(habilitado=True).first()
    )
    if medico is None:
        messages.error(request, 'No hay médicos prescriptores habilitados registrados.')
        return redirect('core:escenario_list')

    try:
        cantidad = max(1, int(request.POST.get('cantidad', '30') or 30))
    except ValueError:
        cantidad = 30

    tipo = request.POST.get('tipo', Receta.TipoReceta.SIMPLE).strip()
    if tipo not in {c[0] for c in Receta.TipoReceta.choices}:
        tipo = Receta.TipoReceta.SIMPLE
    if medicamento.es_controlado and tipo not in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
        tipo = Receta.TipoReceta.RETENIDA
    elif not medicamento.es_controlado and tipo in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
        tipo = Receta.TipoReceta.SIMPLE

    diagnostico = request.POST.get('diagnostico', '').strip() or 'Consulta morbilidad aguda / control en vivo'
    posologia = request.POST.get('posologia', '').strip() or '1 unidad cada 12 horas según indicación médica'
    cronico = request.POST.get('cronico') == 'on'

    hoy = date.today()
    dias_vigencia = 90 if tipo == Receta.TipoReceta.CRONICA else 30

    with transaction.atomic():
        paciente = Paciente.objects.create(
            rut=rut_fmt,
            nombres=nombres,
            apellido_paterno=apellido_paterno,
            apellido_materno=apellido_materno,
            fecha_nacimiento=date(1978, 6, 15),
            sexo='F',
            prevision=prevision,
            cronico=cronico,
        )

        correlativo = Receta.objects.count() + 1
        while Receta.objects.filter(numero_receta=f'REC-LIVE-{correlativo:04d}').exists():
            correlativo += 1
        num_receta = f'REC-LIVE-{correlativo:04d}'

        receta = Receta.objects.create(
            numero_receta=num_receta,
            paciente=paciente,
            medico=medico,
            tipo=tipo,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico=diagnostico,
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=dias_vigencia),
            observaciones=f'Caso inyectado en vivo por docente en escenario "{escenario.nombre}".',
            autorizada_qf=False,
        )
        DetalleReceta.objects.create(
            receta=receta,
            medicamento=medicamento,
            cantidad_prescrita=cantidad,
            posologia=posologia,
            dias_tratamiento=30,
        )

        escenario.pacientes.add(paciente)
        escenario.recetas.add(receta)
        escenario.marcar_actualizado()

        registrar_auditoria(
            request.user,
            'Inyección de Caso Rápido en Escenario',
            f'Escenario "{escenario.nombre}" -> {paciente.nombre_completo} ({receta.numero_receta})',
            valores_nuevos={
                'paciente_rut': paciente.rut,
                'receta': receta.numero_receta,
                'medicamento': medicamento.nombre_generico,
                'cantidad': cantidad,
            },
        )

    messages.success(
        request,
        f'Caso rápido inyectado en "{escenario.nombre}": {paciente.nombre_completo} ({paciente.rut}) con receta {receta.numero_receta} ({medicamento.nombre_generico} x{cantidad}). Se reflejará automáticamente en las pantallas abiertas.'
    )
    return redirect('core:escenario_list')


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para eliminar Escenarios de Simulación.'
)
def escenario_eliminar(request, pk):
    """
    Elimina únicamente la agrupación del escenario (conservando pacientes y recetas en DB).
    Bloquea la eliminación si el escenario se encuentra actualmente activo.
    """
    if request.method != 'POST':
        return redirect('core:escenario_list')

    escenario = get_object_or_404(EscenarioSimulacion, pk=pk)
    if escenario.activo:
        messages.error(request, 'Activa otro escenario antes de eliminar este.')
        return redirect('core:escenario_list')

    nombre = escenario.nombre
    n_pac = escenario.pacientes.count()
    n_rec = escenario.recetas.count()
    escenario.delete()

    registrar_auditoria(
        request.user,
        'Eliminación de Escenario de Simulación',
        f'Escenario "{nombre}"',
        valores_anteriores={'nombre': nombre, 'pacientes_agrupados': n_pac, 'recetas_agrupadas': n_rec},
        valores_nuevos={'pacientes_y_recetas_conservados': True},
    )
    messages.success(
        request,
        f'Escenario "{nombre}" eliminado correctamente. Los pacientes y recetas asociados permanecen intactos en el sistema.'
    )
    return redirect('core:escenario_list')


def _parse_ajax_payload(request):
    """Acepta tanto JSON (application/json) como form-urlencoded/multipart."""
    content_type = request.META.get('CONTENT_TYPE', '') or ''
    if 'application/json' in content_type:
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            return {}
    return request.POST


def _serializar_paciente_escenario(paciente):
    """Serializa un Paciente para insertarlo dinámicamente en el constructor de escenarios."""
    from ges.models import InscripcionGES
    ges_activas = list(
        InscripcionGES.objects.filter(paciente=paciente, activa=True)
        .select_related('patologia')
        .values('patologia__codigo', 'patologia__nombre')
    )
    ges_list = [{'codigo': g['patologia__codigo'], 'nombre': g['patologia__nombre']} for g in ges_activas]
    ges_search = ' '.join(f"{g['codigo']} {g['nombre']}" for g in ges_list)
    search_text = (
        f"{paciente.nombre_completo} {paciente.rut} {paciente.get_prevision_display()} "
        f"{'cronico' if paciente.cronico else ''} {ges_search}"
    ).lower()
    return {
        'id': paciente.pk,
        'rut': paciente.rut,
        'nombre_completo': paciente.nombre_completo,
        'prevision_display': paciente.get_prevision_display(),
        'cronico': paciente.cronico,
        'patologias_ges': ges_list,
        'search_text': search_text,
    }


def _serializar_receta_escenario(receta):
    """Serializa una Receta para insertarla dinámicamente en el constructor de escenarios."""
    detalles = list(receta.detalles.select_related('medicamento').all())
    detalles_resumen = ', '.join(
        f'{d.medicamento.nombre_generico} ({d.cantidad_prescrita})' for d in detalles
    ) or 'Sin ítems prescritos'
    es_vencida = receta.esta_vencida
    estado_badge = 'Vencida' if es_vencida else receta.get_estado_display()
    search_text = (
        f"{receta.numero_receta} {receta.paciente.nombre_completo} {receta.paciente.rut} "
        f"{receta.get_tipo_display()} {estado_badge} {detalles_resumen}"
    ).lower()
    return {
        'id': receta.pk,
        'numero_receta': receta.numero_receta,
        'paciente_id': receta.paciente_id,
        'paciente_nombre': receta.paciente.nombre_completo,
        'paciente_rut': receta.paciente.rut,
        'tipo_display': receta.get_tipo_display(),
        'estado': receta.estado,
        'estado_display': estado_badge,
        'esta_vencida': es_vencida,
        'detalles_resumen': detalles_resumen,
        'search_text': search_text,
    }


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) puede crear pacientes inline desde el constructor de escenarios.'
)
def api_escenario_crear_paciente(request):
    """
    Endpoint JSON AJAX para crear un Paciente desde el modal del constructor de escenarios
    sin recargar la página y sin vincularlo automáticamente a otros escenarios.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    from ges.models import PatologiaGES, InscripcionGES

    data = _parse_ajax_payload(request)
    rut = str(data.get('rut', '') or '').strip()
    nombres = str(data.get('nombres', '') or '').strip()
    apellido_paterno = str(data.get('apellido_paterno', '') or '').strip()
    apellido_materno = str(data.get('apellido_materno', '') or '').strip()
    fecha_nacimiento = str(data.get('fecha_nacimiento', '') or '').strip()
    sexo = str(data.get('sexo', 'F') or 'F').strip()
    prevision = str(data.get('prevision', Paciente.Prevision.FONASA_A) or Paciente.Prevision.FONASA_A).strip()
    cronico_raw = data.get('cronico', False)
    cronico = cronico_raw in (True, 'true', 'True', 'on', '1', 1)
    patologia_ges_id = str(data.get('patologia_ges_id', '') or '').strip()

    tercero_nombre = str(data.get('tercero_autorizado_nombre', '') or '').strip()
    tercero_rut_raw = str(data.get('tercero_autorizado_rut', '') or '').strip()
    tercero_parentesco = str(data.get('tercero_autorizado_parentesco', '') or '').strip()

    if not all([rut, nombres, apellido_paterno, apellido_materno, fecha_nacimiento]):
        return JsonResponse(
            {'ok': False, 'error': 'Completa todos los campos obligatorios (RUT, nombres, apellidos y fecha de nacimiento).'},
            status=400,
        )

    if not validar_rut(rut):
        return JsonResponse(
            {'ok': False, 'error': 'El RUT ingresado no es válido (verifique formato y dígito verificador Módulo 11).'},
            status=400,
        )

    rut_fmt = formatear_rut(rut)
    if Paciente.objects.filter(rut=rut_fmt).exists():
        return JsonResponse(
            {'ok': False, 'error': f'Ya existe un paciente registrado con el RUT {rut_fmt}.'},
            status=400,
        )

    previsiones_validas = {c[0] for c in Paciente.Prevision.choices}
    if prevision not in previsiones_validas:
        return JsonResponse(
            {'ok': False, 'error': 'La previsión debe pertenecer a la red pública (FONASA A-D, PRAIS o Sin Previsión).'},
            status=400,
        )

    if sexo not in ('M', 'F', 'I'):
        sexo = 'F'

    tercero_rut_fmt = ''
    if tercero_rut_raw:
        if not validar_rut(tercero_rut_raw):
            return JsonResponse(
                {'ok': False, 'error': 'El RUT del tercero autorizado no es válido (Módulo 11).'},
                status=400,
            )
        tercero_rut_fmt = formatear_rut(tercero_rut_raw)

    try:
        with transaction.atomic():
            paciente = Paciente.objects.create(
                rut=rut_fmt,
                nombres=nombres,
                apellido_paterno=apellido_paterno,
                apellido_materno=apellido_materno,
                fecha_nacimiento=fecha_nacimiento,
                sexo=sexo,
                prevision=prevision,
                cronico=cronico,
                tercero_autorizado_nombre=tercero_nombre,
                tercero_autorizado_rut=tercero_rut_fmt,
                tercero_autorizado_parentesco=tercero_parentesco,
            )

            if patologia_ges_id.isdigit():
                pat = PatologiaGES.objects.filter(pk=int(patologia_ges_id), activa=True).first()
                if pat:
                    hoy = date.today()
                    InscripcionGES.objects.get_or_create(
                        paciente=paciente,
                        patologia=pat,
                        defaults={
                            'fecha_inscripcion': hoy,
                            'fecha_inicio_periodo': hoy,
                            'fecha_fin_periodo': hoy + timedelta(days=365),
                            'activa': True,
                        },
                    )

            registrar_auditoria(
                request.user,
                'Creación Rápida de Paciente (Constructor de Escenario)',
                f'Paciente {paciente.rut} ({paciente.nombre_completo})',
                valores_nuevos={'rut': paciente.rut, 'prevision': paciente.prevision, 'cronico': paciente.cronico},
            )
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'No fue posible crear el paciente: {e}'}, status=400)

    return JsonResponse({'ok': True, 'paciente': _serializar_paciente_escenario(paciente)}, status=201)


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) puede crear recetas inline desde el constructor de escenarios.'
)
def api_escenario_crear_receta(request):
    """
    Endpoint JSON AJAX para crear una Receta (+ DetalleReceta) desde el modal
    del constructor de escenarios sin recargar la página ni alterar otros escenarios.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    from dispensacion.models import DetalleReceta

    data = _parse_ajax_payload(request)
    paciente_id = str(data.get('paciente_id', '') or '').strip()
    medico_id = str(data.get('medico_id', '') or '').strip()
    medicamento_id = str(data.get('medicamento_id', '') or '').strip()
    tipo = str(data.get('tipo', Receta.TipoReceta.SIMPLE) or Receta.TipoReceta.SIMPLE).strip()
    diagnostico = str(data.get('diagnostico', '') or '').strip()
    posologia = str(data.get('posologia', '') or '').strip() or 'Según indicación médica'
    simular_vencida_raw = data.get('simular_vencida', False)
    simular_vencida = simular_vencida_raw in (True, 'true', 'True', 'on', '1', 1)

    try:
        cantidad = int(data.get('cantidad', 0) or 0)
    except (TypeError, ValueError):
        cantidad = 0

    if not paciente_id.isdigit() or not medico_id.isdigit() or not medicamento_id.isdigit():
        return JsonResponse({'ok': False, 'error': 'Selecciona paciente, médico prescriptor y medicamento.'}, status=400)
    if cantidad <= 0:
        return JsonResponse({'ok': False, 'error': 'La cantidad prescrita debe ser mayor a 0.'}, status=400)
    if not diagnostico:
        return JsonResponse({'ok': False, 'error': 'Ingresa un diagnóstico clínico para la receta.'}, status=400)

    paciente = Paciente.objects.filter(pk=int(paciente_id), activo=True).first()
    medico = MedicoPrescriptor.objects.filter(pk=int(medico_id), habilitado=True).first()
    medicamento = Medicamento.objects.filter(pk=int(medicamento_id), activo=True).first()
    if not paciente or not medico or not medicamento:
        return JsonResponse({'ok': False, 'error': 'Paciente, médico o medicamento no encontrado o inactivo.'}, status=400)

    tipos_validos = {c[0] for c in Receta.TipoReceta.choices}
    if tipo not in tipos_validos:
        tipo = Receta.TipoReceta.SIMPLE

    if medicamento.es_controlado and tipo not in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
        tipo = Receta.TipoReceta.RETENIDA
    elif not medicamento.es_controlado and tipo in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
        tipo = Receta.TipoReceta.SIMPLE

    hoy = date.today()
    if simular_vencida:
        f_emision = hoy - timedelta(days=45)
        f_venc = hoy - timedelta(days=15)
    else:
        f_emision = hoy
        dias_vig = 90 if tipo == Receta.TipoReceta.CRONICA else 30
        f_venc = hoy + timedelta(days=dias_vig)

    try:
        with transaction.atomic():
            correlativo = Receta.objects.count() + 1
            while Receta.objects.filter(numero_receta=f'REC-ESC-{correlativo:04d}').exists():
                correlativo += 1
            num_receta = f'REC-ESC-{correlativo:04d}'

            receta = Receta.objects.create(
                numero_receta=num_receta,
                paciente=paciente,
                medico=medico,
                tipo=tipo,
                estado=Receta.EstadoReceta.PENDIENTE,
                diagnostico=diagnostico,
                fecha_emision=f_emision,
                fecha_vencimiento=f_venc,
                observaciones='Receta creada desde Constructor de Escenarios de Simulación.',
                autorizada_qf=False,
            )
            DetalleReceta.objects.create(
                receta=receta,
                medicamento=medicamento,
                cantidad_prescrita=cantidad,
                posologia=posologia,
                dias_tratamiento=30,
            )
            registrar_auditoria(
                request.user,
                'Creación Rápida de Receta (Constructor de Escenario)',
                f'Receta {receta.numero_receta} ({paciente.rut})',
                valores_nuevos={
                    'tipo': tipo,
                    'medicamento': medicamento.nombre_generico,
                    'cantidad': cantidad,
                    'simular_vencida': simular_vencida,
                },
            )
    except Exception as e:
        return JsonResponse({'ok': False, 'error': f'No fue posible crear la receta: {e}'}, status=400)

    return JsonResponse({'ok': True, 'receta': _serializar_receta_escenario(receta)}, status=201)


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) puede generar casos aleatorios en el constructor de escenarios.'
)
def api_escenario_caso_aleatorio(request):
    """
    Genera vía AJAX un paciente ficticio nuevo (RUT chileno válido único) junto con
    una receta realista pendiente, sin vincularlos a Escenario Base ni a otros escenarios.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido.'}, status=405)

    import random
    from dispensacion.models import DetalleReceta

    medico = MedicoPrescriptor.objects.filter(habilitado=True).order_by('?').first()
    medicamento = Medicamento.objects.filter(activo=True).order_by('?').first()
    if not medico or not medicamento:
        return JsonResponse(
            {'ok': False, 'error': 'Debe existir al menos un médico habilitado y un medicamento activo en el arsenal.'},
            status=400,
        )

    nombres_pool = [
        ('Camila Fernanda', 'F'), ('Sebastián Andrés', 'M'), ('Constanza Belén', 'F'),
        ('Diego Alejandro', 'M'), ('Javiera Antonia', 'F'), ('Cristóbal Ignacio', 'M'),
        ('Francisca Paz', 'F'), ('Felipe Eduardo', 'M'), ('Martina Isidora', 'F'),
        ('Nicolás Patricio', 'M'),
    ]
    apellidos_pool = [
        'Rojas', 'Muñoz', 'Díaz', 'Contreras', 'Sepúlveda', 'Fuentes',
        'Araya', 'Espinoza', 'Valdés', 'Pizarro', 'Cárdenas', 'Navarro',
    ]
    nombre_elegido, sexo_elegido = random.choice(nombres_pool)
    ap_pat = random.choice(apellidos_pool)
    ap_mat = random.choice([a for a in apellidos_pool if a != ap_pat])
    prevision = random.choice([
        Paciente.Prevision.FONASA_A,
        Paciente.Prevision.FONASA_B,
        Paciente.Prevision.FONASA_C,
        Paciente.Prevision.FONASA_D,
        Paciente.Prevision.PRAIS,
    ])
    cronico = random.choice([True, False])
    anio_nac = random.randint(1950, 1998)
    mes_nac = random.randint(1, 12)
    dia_nac = random.randint(1, 28)

    if medicamento.es_controlado:
        tipo_rec = Receta.TipoReceta.RETENIDA
        diagnostico = 'Trastorno de ansiedad / manejo controlado D.S. 404/405'
        cantidad = 30
        posologia = '1 comprimido en la noche según indicación médica'
        dias_vig = 30
    elif cronico:
        tipo_rec = Receta.TipoReceta.CRONICA
        diagnostico = 'Control de patología crónica compensada (PSCV)'
        cantidad = 30
        posologia = '1 unidad cada 24 horas en forma continua'
        dias_vig = 90
    else:
        tipo_rec = Receta.TipoReceta.SIMPLE
        diagnostico = 'Consulta de morbilidad aguda APS'
        cantidad = 20
        posologia = '1 unidad cada 12 horas por 10 días'
        dias_vig = 30

    hoy = date.today()
    with transaction.atomic():
        rut_unico = generar_rut_unico_paciente()
        paciente = Paciente.objects.create(
            rut=rut_unico,
            nombres=nombre_elegido,
            apellido_paterno=ap_pat,
            apellido_materno=ap_mat,
            fecha_nacimiento=date(anio_nac, mes_nac, dia_nac),
            sexo=sexo_elegido,
            prevision=prevision,
            cronico=cronico,
        )

        correlativo = Receta.objects.count() + 1
        while Receta.objects.filter(numero_receta=f'REC-RND-{correlativo:04d}').exists():
            correlativo += 1
        num_receta = f'REC-RND-{correlativo:04d}'

        receta = Receta.objects.create(
            numero_receta=num_receta,
            paciente=paciente,
            medico=medico,
            tipo=tipo_rec,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico=diagnostico,
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=dias_vig),
            observaciones='Caso aleatorio generado desde Constructor de Escenarios.',
            autorizada_qf=False,
        )
        DetalleReceta.objects.create(
            receta=receta,
            medicamento=medicamento,
            cantidad_prescrita=cantidad,
            posologia=posologia,
            dias_tratamiento=30,
        )
        registrar_auditoria(
            request.user,
            'Generación de Caso Aleatorio (Constructor de Escenario)',
            f'{paciente.nombre_completo} ({paciente.rut}) / {receta.numero_receta}',
            valores_nuevos={'medicamento': medicamento.nombre_generico, 'tipo': tipo_rec},
        )

    return JsonResponse({
        'ok': True,
        'paciente': _serializar_paciente_escenario(paciente),
        'receta': _serializar_receta_escenario(receta),
    }, status=201)


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para gestionar el Banco de Pacientes.'
)
def banco_pacientes(request):
    """
    Archivo General Docente (Banco de Pacientes):
    Muestra todos los pacientes creados a nivel general, en qué escenarios participan,
    permite filtrar por escenario o libres (sin asignar), crear pacientes libres y asignarlos.
    """
    from django.db.models import Prefetch
    from ges.models import InscripcionGES, PatologiaGES

    q = request.GET.get('q', '').strip()
    filtro_esc = request.GET.get('escenario', '').strip()

    base_qs = (
        Paciente.objects.filter(activo=True)
        .annotate(
            total_recetas=Count('recetas', distinct=True),
            total_escenarios=Count('escenarios', distinct=True),
        )
        .prefetch_related(
            Prefetch(
                'inscripciones_ges',
                queryset=InscripcionGES.objects.filter(activa=True).select_related('patologia'),
                to_attr='programas_ges_activos',
            ),
            'escenarios',
        )
        .order_by('apellido_paterno', 'apellido_materno', 'nombres')
    )

    total_archivo = base_qs.count()
    total_libres = base_qs.filter(total_escenarios=0).count()
    escenario_activo = EscenarioSimulacion.obtener_activo()
    total_en_activo = (
        escenario_activo.pacientes.filter(activo=True).count() if escenario_activo is not None else 0
    )

    pacientes = base_qs
    if filtro_esc == 'libres':
        pacientes = pacientes.filter(total_escenarios=0)
    elif filtro_esc.isdigit():
        pacientes = pacientes.filter(escenarios__id=int(filtro_esc))

    if q:
        pacientes = pacientes.filter(
            Q(rut__icontains=q) |
            Q(nombres__icontains=q) |
            Q(apellido_paterno__icontains=q) |
            Q(apellido_materno__icontains=q)
        )

    pacientes_lista = list(pacientes)
    for p in pacientes_lista:
        p.escenarios_ids_csv = ','.join(str(e.pk) for e in p.escenarios.all())

    escenarios_todos = EscenarioSimulacion.objects.all().order_by('-activo', 'nombre')
    patologias_ges = PatologiaGES.objects.filter(activa=True).order_by('codigo')

    return render(request, 'core/banco_pacientes.html', {
        'pacientes': pacientes_lista,
        'escenarios_todos': escenarios_todos,
        'patologias_ges': patologias_ges,
        'previsiones': Paciente.Prevision.choices,
        'q': q,
        'filtro_esc': filtro_esc,
        'total_archivo': total_archivo,
        'total_libres': total_libres,
        'total_en_activo': total_en_activo,
    })


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para asignar pacientes a escenarios.'
)
def banco_paciente_asignar_escenarios(request, pk):
    """Asigna o quita escenarios de simulación para un paciente desde el Banco de Pacientes."""
    if request.method != 'POST':
        return redirect('core:banco_pacientes')

    paciente = get_object_or_404(Paciente, pk=pk)
    nuevos_ids = {int(x) for x in request.POST.getlist('escenarios') if str(x).isdigit()}

    with transaction.atomic():
        anteriores_ids = set(paciente.escenarios.values_list('id', flat=True))
        escenarios_seleccionados = EscenarioSimulacion.objects.filter(id__in=nuevos_ids)
        paciente.escenarios.set(escenarios_seleccionados)

        # Si cambió su pertenencia en el escenario activo, notificar a sesiones abiertas sin F5
        esc_activo = EscenarioSimulacion.obtener_activo()
        if esc_activo is not None:
            estaba_en_activo = esc_activo.pk in anteriores_ids
            esta_en_activo = esc_activo.pk in nuevos_ids
            if estaba_en_activo != esta_en_activo:
                esc_activo.marcar_actualizado()

        nombres_nuevos = list(escenarios_seleccionados.values_list('nombre', flat=True))
        registrar_auditoria(
            request.user,
            'Asignación de Paciente a Escenarios',
            f'Paciente {paciente.rut} ({paciente.nombre_completo})',
            valores_anteriores={'escenarios_ids': sorted(anteriores_ids)},
            valores_nuevos={'escenarios': nombres_nuevos},
        )

    if nombres_nuevos:
        messages.success(
            request,
            f'Paciente {paciente.nombre_completo} asignado a: {", ".join(nombres_nuevos)}.'
        )
    else:
        messages.info(
            request,
            f'Paciente {paciente.nombre_completo} quedó libre (sin escenarios asignados).'
        )

    next_query = request.POST.get('next_query', '').strip()
    if next_query:
        return redirect(f"{request.build_absolute_uri('/admin-panel/banco-pacientes/')}?{next_query}")
    return redirect('core:banco_pacientes')
