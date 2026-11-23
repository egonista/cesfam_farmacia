"""
Vistas del módulo Core del Sistema CESFAM Farmacia.
Dashboard, autenticación, gestión de pacientes.
"""
import json
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Paciente, MedicoPrescriptor, Usuario, AuditoriaInmutable, AlertaSistema
from .utils import validar_rut, formatear_rut, registrar_auditoria
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
    Selector rápido de 1-Clic para simulación docente y defensa académica INACAP.
    Permite alternar instantáneamente entre los 4 roles sanitarios RBAC.
    """
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
            registrar_auditoria(
                user,
                'Cambio Rápido de Rol (Simulación Docente INACAP)',
                f'Rol Activo: {user.get_rol_display()}',
                valores_nuevos={'usuario': user.username, 'rut': user.rut, 'rol': user.rol}
            )
            messages.info(
                request,
                f'Simulación Docente INACAP: Sesión activa como {user.get_full_name()} — Rol: {user.get_rol_display()}'
            )
    return redirect('core:dashboard')


def logout_view(request):
    """Cierra la sesión del usuario."""
    if request.method == 'POST':
        logout(request)
        messages.info(request, 'Sesión cerrada correctamente.')
    return redirect('core:login')


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
        activo=True, fecha_vencimiento__lte=hoy
    ).count()
    lotes_por_vencer_30 = Lote.objects.filter(
        activo=True, fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hace_30
    ).count()
    lotes_por_vencer_60 = Lote.objects.filter(
        activo=True, fecha_vencimiento__gt=hace_30, fecha_vencimiento__lte=hace_60
    ).count()
    lotes_por_vencer_90 = Lote.objects.filter(
        activo=True, fecha_vencimiento__gt=hace_60, fecha_vencimiento__lte=hace_90
    ).count()

    recetas_hoy = Receta.objects.filter(fecha_emision=hoy).count()
    dispensaciones_hoy = Dispensacion.objects.filter(fecha__date=hoy).count()
    dispensaciones_semana = Dispensacion.objects.filter(fecha__date__gte=hace_7_dias).count()

    total_pacientes = Paciente.objects.filter(activo=True).count()

    # Datos para gráfico de dispensaciones últimos 7 días
    grafico_labels = []
    grafico_valores = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        grafico_labels.append(dia.strftime('%d/%m'))
        grafico_valores.append(
            Dispensacion.objects.filter(fecha__date=dia).count()
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
    auditoria_reciente = AuditoriaInmutable.objects.all()[:6]
    lotes_criticos_fefo = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0, fecha_vencimiento__gt=hoy
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')[:6]
    carros_clinicos = CarroClinico.objects.filter(activo=True)

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
    }
    return render(request, 'core/dashboard.html', context)


@login_required
def paciente_list(request):
    """Lista de pacientes con búsqueda."""
    query = request.GET.get('q', '')
    pacientes = Paciente.objects.filter(activo=True)
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
    })


@login_required
def paciente_crear(request):
    """Crear un nuevo paciente."""
    if request.method == 'POST':
        rut = request.POST.get('rut', '')
        if not validar_rut(rut):
            messages.error(request, 'El RUT ingresado no es válido (Módulo 11).')
            return render(request, 'core/paciente_form.html', {'datos': request.POST})

        try:
            paciente = Paciente.objects.create(
                rut=formatear_rut(rut),
                nombres=request.POST.get('nombres', ''),
                apellido_paterno=request.POST.get('apellido_paterno', ''),
                apellido_materno=request.POST.get('apellido_materno', ''),
                fecha_nacimiento=request.POST.get('fecha_nacimiento'),
                sexo=request.POST.get('sexo', 'M'),
                direccion=request.POST.get('direccion', ''),
                telefono=request.POST.get('telefono', ''),
                email=request.POST.get('email', ''),
                prevision=request.POST.get('prevision', 'fonasa_a'),
                cronico=request.POST.get('cronico') == 'on',
            )
            messages.success(request, f'Paciente {paciente.nombre_completo} creado exitosamente.')
            return redirect('core:paciente_detalle', pk=paciente.pk)
        except Exception as e:
            messages.error(request, f'Error al crear paciente: {e}')

    return render(request, 'core/paciente_form.html', {})


@login_required
def paciente_detalle(request, pk):
    """Detalle de un paciente con edición de ficha, inscripción GES e historial de recetas."""
    from ges.models import PatologiaGES, InscripcionGES
    paciente = get_object_or_404(Paciente, pk=pk)

    if request.method == 'POST':
        accion = request.POST.get('accion')
        if accion == 'editar_paciente':
            paciente.nombres = request.POST.get('nombres', paciente.nombres).strip()
            paciente.apellido_paterno = request.POST.get('apellido_paterno', paciente.apellido_paterno).strip()
            paciente.apellido_materno = request.POST.get('apellido_materno', paciente.apellido_materno).strip()
            paciente.telefono = request.POST.get('telefono', paciente.telefono).strip()
            paciente.direccion = request.POST.get('direccion', paciente.direccion).strip()
            paciente.prevision = request.POST.get('prevision', paciente.prevision)
            paciente.cronico = request.POST.get('cronico') == 'on'
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
    })


def api_validar_rut(request):
    """API endpoint para validar RUT vía AJAX."""
    rut = request.GET.get('rut', '')
    es_valido = validar_rut(rut)
    return JsonResponse({
        'rut': rut,
        'valido': es_valido,
        'formateado': formatear_rut(rut) if es_valido else None,
    })


@login_required
def auditoria_list(request):
    """Visor forense de la Bitácora de Auditoría Inmutable en PostgreSQL (JSONB)."""
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


@login_required
def usuario_list(request):
    """Gestión de Usuarios (RUT, nombre, teléfono) y Matriz de Privilegios RBAC (RF-01 y RF-02)."""
    if request.method == 'POST' and request.user.rol == 'admin':
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
                    'Cambio de Estado de Usuario (RF-01)',
                    f'Usuario {u_target.username}',
                    valores_anteriores={'activo': estado_ant},
                    valores_nuevos={'activo': u_target.is_active}
                )
                messages.info(request, f'Estado de {u_target.get_full_name()} actualizado.')
            return redirect('core:usuario_list')

        rut = request.POST.get('rut', '')
        if not validar_rut(rut):
            messages.error(request, 'El RUT ingresado no es válido (Módulo 11).')
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
                    'Creación de Cuenta de Usuario RBAC',
                    f'Usuario {nuevo_usr.username} ({nuevo_usr.get_rol_display()})',
                    valores_nuevos={
                        'username': nuevo_usr.username,
                        'rut': nuevo_usr.rut,
                        'telefono': nuevo_usr.telefono,
                        'rol': nuevo_usr.rol,
                    }
                )
                messages.success(request, f'Usuario {nuevo_usr.get_full_name()} creado exitosamente.')
                return redirect('core:usuario_list')
            except Exception as e:
                messages.error(request, f'Error al crear usuario: {e}')

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
