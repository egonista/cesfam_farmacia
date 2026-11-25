"""
Vistas del módulo Dispensación del Sistema CESFAM Farmacia.
Control de concurrencia, validación estricta de vigencia, cuotas GES,
priorización por vencimiento (FEFO) y retiro por tercero autorizado.
"""
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Q, F
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import Receta, DetalleReceta, Dispensacion, DetalleDispensacion, TerceroAutorizado
from core.models import Paciente, MedicoPrescriptor, EscenarioSimulacion
from core.utils import (
    validar_rut,
    formatear_rut,
    registrar_auditoria,
    obtener_rol_efectivo,
    obtener_filtro_escenario,
)
from core.decorators import rol_requerido, denegar_acceso
from farmacia.models import Medicamento, Lote, MovimientoStock
from ges.models import InscripcionGES, CanastaGES, CuotaGES
from controlados.models import LibroControlados


def _parse_date(val):
    if isinstance(val, date):
        return val
    if not val:
        return date.today()
    return datetime.strptime(str(val), '%Y-%m-%d').date()


def _inferir_via_administracion(medicamento):
    """Infiere una vía de administración clínica coherente según forma farmacéutica o unidad."""
    forma = (medicamento.forma_farmaceutica or '').lower()
    unidad = (medicamento.unidad_medida or '').lower()
    if unidad == 'inhalador' or 'inhal' in forma or 'aerosol' in forma:
        return 'Vía inhalatoria'
    if unidad == 'amp' or 'ampolla' in forma or 'inyectable' in forma or 'jeringa' in forma:
        return 'Vía parenteral'
    if unidad == 'tubo' or any(k in forma for k in ('crema', 'pomada', 'ungüento', 'gel', 'tópica')):
        return 'Vía tópica'
    if any(k in forma for k in ('oftálm', 'colirio')):
        return 'Vía oftálmica'
    if 'óvulo' in forma or 'vaginal' in forma:
        return 'Vía vaginal'
    if 'supositorio' in forma or 'rectal' in forma:
        return 'Vía rectal'
    if any(k in forma for k in ('comprimido', 'cápsula', 'jarabe', 'suspensión', 'solución oral', 'gotas')) or unidad in ('comp', 'cap', 'sobre'):
        return 'Vía oral'
    return 'Según indicación médica'


def _construir_contexto_documento_receta(receta, incluir_lotes=False):
    """Construye el contexto clínico unificado para ficha, modal y documento formal de impresión."""
    detalles = receta.detalles.all().select_related('medicamento')
    detalles_con_lotes = []
    for detalle in detalles:
        lotes_fefo = detalle.medicamento.lotes_fefo() if incluir_lotes else Lote.objects.none()
        lote_sugerido = lotes_fefo.first() if incluir_lotes and lotes_fefo.exists() else None
        detalles_con_lotes.append({
            'detalle': detalle,
            'via_administracion': _inferir_via_administracion(detalle.medicamento),
            'lotes_fefo': lotes_fefo,
            'lote_sugerido': lote_sugerido,
        })

    hoy = date.today()
    fn = receta.paciente.fecha_nacimiento
    edad_paciente = hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day)) if fn else None

    inscripciones_ges = InscripcionGES.objects.filter(
        paciente=receta.paciente, activa=True
    ).select_related('patologia')

    entregas_receta = DetalleDispensacion.objects.filter(
        dispensacion__receta=receta
    ).select_related(
        'dispensacion',
        'dispensacion__usuario_dispensador',
        'dispensacion__tercero_autorizado',
        'detalle_receta__medicamento',
        'lote',
    ).order_by('-dispensacion__fecha')

    tercero_conocido = (
        TerceroAutorizado.objects.filter(dispensaciones__receta=receta)
        .order_by('-dispensaciones__fecha')
        .first()
        or TerceroAutorizado.objects.filter(dispensaciones__receta__paciente=receta.paciente)
        .order_by('-dispensaciones__fecha')
        .first()
    )

    ultima_dispensacion = (
        receta.dispensaciones.select_related('usuario_dispensador', 'tercero_autorizado')
        .order_by('-fecha')
        .first()
    )

    return {
        'receta': receta,
        'detalles_con_lotes': detalles_con_lotes,
        'edad_paciente': edad_paciente,
        'inscripciones_ges': inscripciones_ges,
        'tercero_conocido': tercero_conocido,
        'entregas_receta': entregas_receta,
        'ultima_dispensacion': ultima_dispensacion,
    }


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para ver ni gestionar recetas médicas.'
)
def receta_list(request):
    """Lista de recetas médicas con búsqueda y filtro por estado."""
    query = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '').strip()

    escenario_activo, filtrar_por_escenario, vista_escenario = obtener_filtro_escenario(request)
    total_recetas_completo = Receta.objects.count()
    total_recetas_escenario = (
        escenario_activo.recetas.count() if escenario_activo is not None else total_recetas_completo
    )
    recetas = Receta.objects.all().select_related('paciente', 'medico')
    escenario_sin_recetas = False
    if filtrar_por_escenario and escenario_activo is not None:
        recetas = recetas.filter(
            id__in=escenario_activo.recetas.values_list('id', flat=True)
        )
        escenario_sin_recetas = not escenario_activo.recetas.exists()
    if query:
        recetas = recetas.filter(
            Q(numero_receta__icontains=query) |
            Q(paciente__rut__icontains=query) |
            Q(paciente__nombres__icontains=query) |
            Q(paciente__apellido_paterno__icontains=query)
        )
    if estado:
        recetas = recetas.filter(estado=estado)

    return render(request, 'dispensacion/receta_list.html', {
        'recetas': recetas[:60],
        'query': query,
        'estado': estado,
        'estados': Receta.EstadoReceta.choices,
        'vista_escenario': vista_escenario,
        'filtrar_por_escenario': filtrar_por_escenario,
        'total_recetas_completo': total_recetas_completo,
        'total_recetas_escenario': total_recetas_escenario,
        'escenario_sin_recetas': escenario_sin_recetas,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para registrar ni precargar recetas médicas.'
)
@transaction.atomic
def receta_crear(request):
    """Registrar y validar una nueva receta médica (Precarga por Admin o transcripción en mostrador por Farmacia)."""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                numero_receta = request.POST.get('numero_receta', '').strip()
                if not numero_receta:
                    correlativo = Receta.objects.count() + 1
                    while Receta.objects.filter(numero_receta=f'REC-2026-{correlativo:04d}').exists():
                        correlativo += 1
                    numero_receta = f'REC-2026-{correlativo:04d}'
                if Receta.objects.filter(numero_receta__iexact=numero_receta).exists():
                    raise ValueError(f'Ya existe una receta registrada con el número {numero_receta}.')

                paciente = Paciente.objects.get(pk=request.POST.get('paciente'))
                medico = MedicoPrescriptor.objects.get(pk=request.POST.get('medico'))

                if not medico.habilitado:
                    raise ValueError('El médico prescriptor seleccionado no se encuentra habilitado para emitir recetas.')

                tipo = request.POST.get('tipo', 'simple')
                f_emision = _parse_date(request.POST.get('fecha_emision'))
                f_venc = _parse_date(request.POST.get('fecha_vencimiento'))

                if f_venc < f_emision:
                    raise ValueError('La fecha de vencimiento no puede ser anterior a la fecha de emisión de la receta.')

                if tipo != Receta.TipoReceta.CRONICA and (date.today() - f_emision).days > 30:
                    raise ValueError('No se puede registrar una receta emitida hace más de 30 días, ya que su vigencia se encuentra expirada.')

                medicamento_ids = request.POST.getlist('medicamento_id') or request.POST.getlist('medicamento')
                cantidades = request.POST.getlist('cantidad') or request.POST.getlist('cantidad_prescrita')
                posologias = request.POST.getlist('posologia')
                dias_trat = request.POST.getlist('dias_tratamiento') or request.POST.getlist('duracion_dias')

                items_validos = []
                for i in range(len(medicamento_ids)):
                    if medicamento_ids[i]:
                        cant_val = int(cantidades[i]) if i < len(cantidades) and cantidades[i] else 0
                        if cant_val <= 0:
                            raise ValueError('La cantidad prescrita de cada medicamento debe ser mayor a cero.')
                        dias_val = int(dias_trat[i]) if i < len(dias_trat) and dias_trat[i] else 30
                        pos_val = posologias[i].strip() if i < len(posologias) and posologias[i].strip() else 'Según indicación médica'
                        med_obj = Medicamento.objects.get(pk=int(medicamento_ids[i]))
                        items_validos.append((med_obj, cant_val, pos_val, dias_val))

                if not items_validos:
                    raise ValueError('Debe incluir al menos un medicamento en la receta.')

                tiene_controlado = any(med_obj.es_controlado for med_obj, _, _, _ in items_validos)
                if tiene_controlado:
                    if tipo not in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
                        tipo = Receta.TipoReceta.RETENIDA
                    if (f_venc - f_emision).days > 30:
                        f_venc = f_emision + timedelta(days=30)
                else:
                    if tipo in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
                        tipo = Receta.TipoReceta.SIMPLE
                        messages.info(
                            request,
                            'Los medicamentos indicados no son psicotrópicos ni estupefacientes; la receta fue registrada como Receta Simple.'
                        )

                receta = Receta.objects.create(
                    numero_receta=numero_receta,
                    paciente=paciente,
                    medico=medico,
                    tipo=tipo,
                    diagnostico=request.POST.get('diagnostico', '').strip(),
                    fecha_emision=f_emision,
                    fecha_vencimiento=f_venc,
                    observaciones=request.POST.get('observaciones', '').strip(),
                    autorizada_qf=False,
                )

                for med_obj, cant_val, pos_val, dias_val in items_validos:
                    DetalleReceta.objects.create(
                        receta=receta,
                        medicamento=med_obj,
                        cantidad_prescrita=cant_val,
                        posologia=pos_val,
                        dias_tratamiento=dias_val,
                    )

                if obtener_rol_efectivo(request) in ('tecnico', 'quimico'):
                    escenario_activo = EscenarioSimulacion.obtener_activo()
                    if escenario_activo is not None:
                        escenario_activo.recetas.add(receta)
                        escenario_activo.pacientes.add(paciente)
                        escenario_activo.marcar_actualizado()

                registrar_auditoria(
                    request.user,
                    'Registro de Receta Médica',
                    f'Receta {receta.numero_receta}',
                    valores_nuevos={'paciente': paciente.rut, 'medico': medico.rut, 'tipo': tipo}
                )
                messages.success(request, f'Receta {receta.numero_receta} registrada correctamente.')
                if request.POST.get('ir_a_dispensar') == '1' and request.user.rol in ('quimico', 'tecnico'):
                    return redirect('dispensacion:dispensar_receta', receta_pk=receta.pk)
                return redirect('dispensacion:receta_detalle', pk=receta.pk)
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No fue posible registrar la receta: {e}')

    pacientes = Paciente.objects.filter(activo=True)
    escenario_activo, filtrar_por_escenario, _ = obtener_filtro_escenario(request)
    if filtrar_por_escenario and escenario_activo is not None and obtener_rol_efectivo(request) in ('tecnico', 'quimico'):
        pacientes = pacientes.filter(
            id__in=escenario_activo.pacientes.values_list('id', flat=True)
        )
    medicos = MedicoPrescriptor.objects.filter(habilitado=True)
    medicamentos = Medicamento.objects.filter(activo=True)

    return render(request, 'dispensacion/receta_form.html', {
        'pacientes': pacientes,
        'medicos': medicos,
        'medicamentos': medicamentos,
        'tipos_receta': Receta.TipoReceta.choices,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para consultar ni editar recetas médicas.'
)
@transaction.atomic
def receta_detalle(request, pk):
    """
    Detalle clínico de receta médica:
    - Técnico en Farmacia solo consulta detalle, lotes FEFO e historial (bloqueado 403 en edición/anulación).
    - Agregar/eliminar medicamentos de una receta emitida queda restringido al Administrador.
    - Anular/reactivar receta queda habilitado solo para Químico Farmacéutico y Administrador con motivo obligatorio.
    """
    receta = get_object_or_404(
        Receta.objects.select_related('paciente', 'medico', 'qf_autorizador'),
        pk=pk
    )

    if request.method == 'POST':
        accion = request.POST.get('accion', '').strip()

        if accion in ('agregar_medicamento_receta', 'eliminar_detalle_receta'):
            if request.user.rol != 'admin':
                return denegar_acceso(
                    request,
                    motivo='Solo el Administrador (Docente) puede agregar o eliminar medicamentos en una receta médica ya emitida.',
                    roles_autorizados=('admin',)
                )
            if receta.estado in ('pendiente', 'parcial', 'anulada'):
                if accion == 'agregar_medicamento_receta':
                    med = get_object_or_404(Medicamento, pk=request.POST.get('medicamento_id'))
                    cant = int(request.POST.get('cantidad_prescrita', 30) or 30)
                    posologia = request.POST.get('posologia', '1 comprimido cada 12 horas').strip()
                    dias = int(request.POST.get('dias_tratamiento', 30) or 30)
                    if cant <= 0:
                        messages.error(request, 'La cantidad prescrita debe ser mayor a cero.')
                    else:
                        DetalleReceta.objects.create(
                            receta=receta,
                            medicamento=med,
                            cantidad_prescrita=cant,
                            posologia=posologia,
                            dias_tratamiento=dias,
                        )
                        if med.es_controlado:
                            if receta.tipo not in (Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE):
                                receta.tipo = Receta.TipoReceta.RETENIDA
                            if (receta.fecha_vencimiento - receta.fecha_emision).days > 30:
                                receta.fecha_vencimiento = receta.fecha_emision + timedelta(days=30)
                            receta.autorizada_qf = False
                            receta.save()
                        registrar_auditoria(
                            request.user,
                            'Adición de Medicamento a Receta Médica',
                            f'Receta {receta.numero_receta}',
                            valores_nuevos={'medicamento': med.nombre_generico, 'cantidad': cant}
                        )
                        messages.success(request, f'Se agregó {med.nombre_generico} ({cant} unidades) a la receta.')
                    return redirect('dispensacion:receta_detalle', pk=receta.pk)

                elif accion == 'eliminar_detalle_receta':
                    det = get_object_or_404(DetalleReceta, pk=request.POST.get('detalle_id'), receta=receta)
                    if det.cantidad_dispensada == 0:
                        nombre_m = det.medicamento.nombre_generico
                        det.delete()
                        registrar_auditoria(
                            request.user,
                            'Eliminación de Medicamento en Receta Médica',
                            f'Receta {receta.numero_receta}',
                            valores_anteriores={'medicamento_eliminado': nombre_m}
                        )
                        messages.warning(request, f'Se quitó {nombre_m} de la receta.')
                    else:
                        messages.error(request, 'No se puede quitar un medicamento que ya registra entregas previas.')
                    return redirect('dispensacion:receta_detalle', pk=receta.pk)

        elif accion in ('anular_receta', 'reactivar_receta'):
            if request.user.rol not in ('admin', 'quimico'):
                return denegar_acceso(
                    request,
                    motivo='Solo el Químico Farmacéutico o el Administrador están autorizados para anular o reactivar recetas médicas.',
                    roles_autorizados=('quimico', 'admin')
                )
            if accion == 'anular_receta' and receta.estado in ('pendiente', 'parcial'):
                motivo_anulacion = request.POST.get('motivo_anulacion', '').strip()
                if not motivo_anulacion:
                    messages.error(request, 'Debe ingresar un motivo obligatorio para anular la receta médica.')
                    return redirect('dispensacion:receta_detalle', pk=receta.pk)
                estado_ant = receta.estado
                receta.estado = Receta.EstadoReceta.ANULADA
                sello_anulacion = (
                    f"[ANULADA por {request.user.get_full_name()} ({request.user.get_rol_display()}) "
                    f"el {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')}]: {motivo_anulacion}"
                )
                receta.observaciones = (
                    f"{receta.observaciones}\n{sello_anulacion}".strip()
                    if receta.observaciones else sello_anulacion
                )
                receta.save()
                registrar_auditoria(
                    request.user,
                    'Anulación de Receta Médica',
                    f'Receta {receta.numero_receta}',
                    valores_anteriores={'estado': estado_ant},
                    valores_nuevos={
                        'estado': 'anulada',
                        'motivo_anulacion': motivo_anulacion,
                        'fecha_hora': timezone.localtime(timezone.now()).isoformat(),
                    }
                )
                messages.warning(request, f'La receta {receta.numero_receta} fue anulada. Motivo registrado en auditoría.')
                return redirect('dispensacion:receta_detalle', pk=receta.pk)

            elif accion == 'reactivar_receta' and receta.estado == 'anulada':
                receta.estado = Receta.EstadoReceta.PENDIENTE
                receta.save()
                registrar_auditoria(
                    request.user,
                    'Reactivación de Receta Médica',
                    f'Receta {receta.numero_receta}',
                    valores_anteriores={'estado': 'anulada'},
                    valores_nuevos={'estado': 'pendiente'}
                )
                messages.info(request, f'La receta {receta.numero_receta} fue reactivada como pendiente.')
                return redirect('dispensacion:receta_detalle', pk=receta.pk)

    ctx_doc = _construir_contexto_documento_receta(receta, incluir_lotes=True)
    ctx_doc['todos_medicamentos'] = Medicamento.objects.filter(activo=True).order_by('nombre_generico')
    return render(request, 'dispensacion/receta_detalle.html', ctx_doc)


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para imprimir ni consultar recetas médicas.'
)
def receta_imprimir(request, pk):
    """Vista dedicada y limpia para impresión formal del Documento de Receta Médica."""
    receta = get_object_or_404(
        Receta.objects.select_related('paciente', 'medico', 'qf_autorizador'),
        pk=pk
    )
    ctx_doc = _construir_contexto_documento_receta(receta, incluir_lotes=False)
    ctx_doc['autoprint'] = request.GET.get('autoprint') == '1'
    return render(request, 'dispensacion/receta_imprimir.html', ctx_doc)


@rol_requerido(
    'quimico',
    motivo='Solo el Químico Farmacéutico puede firmar y autorizar la entrega de recetas controladas o retenidas.'
)
@transaction.atomic
def autorizar_receta_qf(request, pk):
    """Autorización / firma técnica del Químico Farmacéutico para habilitar recetas controladas al Técnico."""
    receta = get_object_or_404(Receta.objects.select_for_update(of=('self',)), pk=pk)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')

    if request.method != 'POST':
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    pin = request.POST.get('pin_qf', '').strip()
    pin_valido = False
    if pin:
        if request.user.pin_seguridad:
            from django.contrib.auth.hashers import check_password
            pin_valido = check_password(pin, request.user.pin_seguridad)
        else:
            pin_valido = pin == '123456'
    if not pin_valido:
        messages.error(request, 'PIN de autorización del Químico Farmacéutico incorrecto. Receta no autorizada.')
        return redirect(next_url or 'dispensacion:dispensar')

    if receta.esta_vencida:
        messages.error(request, f'La receta {receta.numero_receta} se encuentra vencida y no puede ser autorizada.')
        return redirect(next_url or 'dispensacion:dispensar')

    receta.autorizada_qf = True
    receta.qf_autorizador = request.user
    receta.fecha_autorizacion_qf = timezone.now()
    receta.save(update_fields=['autorizada_qf', 'qf_autorizador', 'fecha_autorizacion_qf'])

    registrar_auditoria(
        request.user,
        'Autorización Q.F. de Receta Controlada / Retenida',
        f'Receta {receta.numero_receta}',
        valores_anteriores={'autorizada_qf': False},
        valores_nuevos={
            'autorizada_qf': True,
            'qf_autorizador': request.user.get_full_name(),
            'paciente': receta.paciente.rut,
        }
    )
    messages.success(
        request,
        f'Receta {receta.numero_receta} autorizada y firmada por Q.F. {request.user.get_full_name()}. Ya puede ser dispensada en ventanilla.'
    )
    return redirect(next_url or 'dispensacion:dispensar')


@rol_requerido(
    'quimico', 'tecnico',
    motivo='La operación del mostrador diario y dispensación de medicamentos a pacientes está reservada exclusivamente al Técnico en Farmacia y al Químico Farmacéutico.'
)
def dispensar(request):
    """
    Ventanilla de Atención y Dispensación Asistencial:
    - Busca por RUT, nombre del paciente o N° de receta.
    - Organiza las recetas en 4 pestañas operativas: Listas para Entregar (por defecto),
      Pendientes Q.F., Vencidas y Todas.
    - Precalcula disponibilidad en vitrina/bodega y vigencia relativa para evitar consultas N+1.
    """
    q = request.GET.get('q', '').strip()
    filtro = request.GET.get('filtro', 'listas').strip()
    if filtro not in ('listas', 'pendientes_qf', 'vencidas', 'todas'):
        filtro = 'listas'

    recetas_base = (
        Receta.objects.filter(estado__in=['pendiente', 'parcial', 'vencida'])
        .select_related('paciente', 'medico', 'qf_autorizador')
        .prefetch_related('detalles__medicamento__lotes__ubicacion')
        .order_by('-fecha_emision', '-id')
    )

    escenario_activo, filtrar_por_escenario, _ = obtener_filtro_escenario(request)
    escenario_sin_recetas = False
    if filtrar_por_escenario and escenario_activo is not None:
        recetas_base = recetas_base.filter(
            id__in=escenario_activo.recetas.values_list('id', flat=True)
        )
        escenario_sin_recetas = not escenario_activo.recetas.exists()

    if q:
        recetas_base = recetas_base.filter(
            Q(paciente__rut__icontains=q) |
            Q(paciente__nombres__icontains=q) |
            Q(paciente__apellido_paterno__icontains=q) |
            Q(paciente__apellido_materno__icontains=q) |
            Q(numero_receta__icontains=q)
        )

    hoy = date.today()
    todas_items = []
    listas_items = []
    pendientes_qf_items = []
    vencidas_items = []

    for r in recetas_base:
        # Calcular detalles y stock disponible en Vitrina vs Bodega sin N+1
        detalles_stock = []
        for det in r.detalles.all():
            lotes_vigentes = [
                l for l in det.medicamento.lotes.all()
                if l.activo and not l.en_cuarentena and l.cantidad_actual > 0 and l.fecha_vencimiento > hoy
            ]
            stock_vitrina = sum(l.cantidad_actual for l in lotes_vigentes if l.ubicacion.tipo == 'vitrina')
            stock_bodega = sum(l.cantidad_actual for l in lotes_vigentes if l.ubicacion.tipo == 'bodega')
            detalles_stock.append({
                'detalle': det,
                'stock_vitrina': stock_vitrina,
                'stock_bodega': stock_bodega,
                'vitrina_suficiente': stock_vitrina >= det.cantidad_pendiente and stock_vitrina > 0,
            })

        dias_diff = (r.fecha_vencimiento - hoy).days
        es_vencida = r.esta_vencida
        req_qf = (not es_vencida) and r.es_controlada and (not r.autorizada_qf)

        if es_vencida:
            if dias_diff < 0:
                vigencia_label = f'Vencida hace {abs(dias_diff)} día{"s" if abs(dias_diff) != 1 else ""}'
            else:
                vigencia_label = 'Plazo 30 días expirado'
        elif dias_diff == 0:
            vigencia_label = 'Vence hoy'
        elif dias_diff == 1:
            vigencia_label = 'Vence mañana'
        else:
            vigencia_label = f'Vence en {dias_diff} días'

        item = {
            'receta': r,
            'detalles_stock': detalles_stock,
            'es_vencida': es_vencida,
            'requiere_qf': req_qf,
            'dias_diff': dias_diff,
            'vigencia_label': vigencia_label,
        }
        todas_items.append(item)
        if es_vencida:
            vencidas_items.append(item)
        elif req_qf:
            pendientes_qf_items.append(item)
        else:
            listas_items.append(item)

    if filtro == 'pendientes_qf':
        recetas_mostradas = pendientes_qf_items
    elif filtro == 'vencidas':
        recetas_mostradas = vencidas_items
    elif filtro == 'todas':
        recetas_mostradas = todas_items
    else:
        recetas_mostradas = listas_items

    pacientes = Paciente.objects.filter(activo=True)
    if filtrar_por_escenario and escenario_activo is not None:
        pacientes = pacientes.filter(
            id__in=escenario_activo.pacientes.values_list('id', flat=True)
        )
    medicos = MedicoPrescriptor.objects.filter(habilitado=True)
    medicamentos = Medicamento.objects.filter(activo=True)
    hoy_str = hoy.isoformat()
    venc_30_str = (hoy + timedelta(days=30)).isoformat()

    return render(request, 'dispensacion/dispensar.html', {
        'recetas_mostradas': recetas_mostradas,
        'q': q,
        'filtro': filtro,
        'total_listas': len(listas_items),
        'total_pendientes_qf': len(pendientes_qf_items),
        'total_vencidas': len(vencidas_items),
        'total_todas': len(todas_items),
        'pacientes': pacientes,
        'medicos': medicos,
        'medicamentos': medicamentos,
        'tipos_receta': Receta.TipoReceta.choices,
        'hoy_str': hoy_str,
        'venc_30_str': venc_30_str,
        'escenario_sin_recetas': escenario_sin_recetas,
    })


@rol_requerido(
    'quimico', 'tecnico',
    motivo='Solo el Técnico en Farmacia y el Químico Farmacéutico pueden dispensar medicamentos a pacientes.'
)
@transaction.atomic
def dispensar_receta(request, receta_pk):
    """
    Proceso transaccional atómico de dispensación asistencial:
    - Bloquea la fila de Receta, DetalleReceta y Lotes con SELECT FOR UPDATE para impedir condiciones de carrera.
    - Rechaza retiros duplicados, recetas vencidas (>30 días o fecha_vencimiento < hoy) o anuladas, y cuotas GES agotadas.
    - Bloquea al Técnico en Farmacia si la receta es controlada/retenida sin visto bueno del Q.F.
    """
    receta = get_object_or_404(
        Receta.objects.select_for_update(of=('self',)).select_related('paciente', 'medico', 'qf_autorizador'),
        pk=receta_pk
    )

    # 1. Bloqueo estricto de retiro duplicado / receta ya cerrada
    if receta.estado == Receta.EstadoReceta.DISPENSADA_TOTAL:
        ultima_disp = receta.dispensaciones.order_by('-fecha').first()
        fecha_str = ultima_disp.fecha.strftime('%d/%m/%Y') if ultima_disp else 'anteriormente'
        messages.error(request, f'Esta receta ya fue dispensada en su totalidad el {fecha_str}. No se permiten entregas duplicadas.')
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    if receta.estado == Receta.EstadoReceta.ANULADA:
        messages.error(request, 'Esta receta fue anulada y no puede ser dispensada.')
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    # 2. Control estricto de vigencia (fecha_vencimiento < hoy o > 30 días desde emisión)
    if not receta.esta_vigente or receta.esta_vencida:
        msg_venc = (
            f'Esta receta se encuentra VENCIDA (emisión: {receta.fecha_emision.strftime("%d/%m/%Y")}, '
            f'vencimiento: {receta.fecha_vencimiento.strftime("%d/%m/%Y")}) y su entrega está bloqueada.'
        )
        if request.method == 'POST':
            registrar_auditoria(
                request.user,
                'Intento Bloqueado de Dispensación de Receta Vencida',
                f'Receta {receta.numero_receta}',
                valores_nuevos={'fecha_vencimiento': receta.fecha_vencimiento.isoformat(), 'rol': request.user.rol}
            )
            if request.headers.get('Accept', '').startswith('application/json'):
                return JsonResponse({'error': msg_venc}, status=400)
        messages.error(request, msg_venc)
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    # 3. Bloqueo estricto para Técnico si la receta es Controlada/Retenida sin visto bueno del Q.F.
    if receta.es_controlada and not receta.autorizada_qf and request.user.rol == 'tecnico':
        return denegar_acceso(
            request,
            motivo=(
                f'La receta {receta.numero_receta} corresponde a medicamentos controlados/retenidos y aún no cuenta '
                f'con la autorización previa del Químico Farmacéutico.'
            ),
            roles_autorizados=('quimico',)
        )

    if not receta.medico.habilitado:
        messages.error(request, 'El médico prescriptor no cuenta con habilitación vigente.')
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    detalles = list(
        receta.detalles.select_for_update().select_related('medicamento').filter(
            cantidad_dispensada__lt=models.F('cantidad_prescrita')
        )
    )

    if not detalles:
        messages.error(request, 'Esta receta no tiene medicamentos con saldo pendiente de entrega.')
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Validar datos del tercero autorizado si corresponde
                retiro_tercero = request.POST.get('retiro_tercero') == 'on'
                tercero = None

                if retiro_tercero:
                    rut_tercero = request.POST.get('rut_tercero', '').strip()
                    nombres_t = request.POST.get('nombres_tercero', '').strip()
                    ap_pat_t = request.POST.get('ap_paterno_tercero', '').strip()
                    ap_mat_t = request.POST.get('ap_materno_tercero', '').strip()
                    parentesco_t = request.POST.get('parentesco_tercero', '').strip()
                    telefono_t = request.POST.get('telefono_tercero', '').strip()

                    if not validar_rut(rut_tercero):
                        raise ValueError('El RUT ingresado para la persona que retira no es válido.')
                    if not nombres_t or not ap_pat_t or not parentesco_t or not telefono_t:
                        raise ValueError('Debe completar el nombre, parentesco y teléfono de la persona autorizada que retira.')

                    tercero = TerceroAutorizado.objects.create(
                        rut=formatear_rut(rut_tercero),
                        nombres=nombres_t,
                        apellido_paterno=ap_pat_t,
                        apellido_materno=ap_mat_t,
                        parentesco=parentesco_t,
                        telefono=telefono_t,
                    )

                # Pre-validar todas las líneas a dispensar antes de efectuar cargos
                operaciones_preparadas = []
                for detalle in detalles:
                    lote_id = request.POST.get(f'lote_{detalle.id}')
                    cantidad_str = request.POST.get(f'cantidad_{detalle.id}', '0')
                    cantidad = int(cantidad_str) if cantidad_str else 0

                    if cantidad < 0:
                        raise ValueError('La cantidad a entregar no puede ser negativa.')
                    if cantidad == 0 or not lote_id:
                        continue

                    if cantidad > detalle.cantidad_pendiente:
                        raise ValueError(
                            f'La cantidad indicada ({cantidad}) supera el saldo pendiente de la receta '
                            f'({detalle.cantidad_pendiente}) para {detalle.medicamento.nombre_generico}.'
                        )

                    # Bloqueo a nivel de fila (SELECT FOR UPDATE) sobre el Lote para evitar condiciones de carrera
                    lote = Lote.objects.select_for_update().get(pk=lote_id)

                    if lote.medicamento_id != detalle.medicamento_id:
                        raise ValueError('El lote seleccionado no corresponde al medicamento prescrito.')

                    if lote.esta_vencido:
                        raise ValueError(
                            f'El lote {lote.numero_lote} de {detalle.medicamento.nombre_generico} está vencido '
                            f'({lote.fecha_vencimiento.strftime("%d/%m/%Y")}) y no puede ser entregado.'
                        )

                    if not lote.puede_dispensar(detalle.dias_tratamiento):
                        raise ValueError(
                            f'El lote {lote.numero_lote} vence en {lote.dias_para_vencer} días, lo cual no cubre '
                            f'los {detalle.dias_tratamiento} días de tratamiento prescritos.'
                        )

                    if cantidad > lote.cantidad_actual:
                        raise ValueError(
                            f'Stock insuficiente en el lote {lote.numero_lote} de {detalle.medicamento.nombre_generico}. '
                            f'Disponible: {lote.cantidad_actual} unidades.'
                        )

                    # Verificar cobertura y saldo de cuotas del programa de salud (GES / Crónico)
                    inscripcion_ges = InscripcionGES.objects.select_for_update().filter(
                        paciente=receta.paciente,
                        activa=True,
                        patologia__canastas__medicamento=detalle.medicamento
                    ).first()
                    canasta_ges = None
                    prox_numero_cuota = None

                    if inscripcion_ges:
                        canasta_ges = CanastaGES.objects.filter(
                            patologia=inscripcion_ges.patologia,
                            medicamento=detalle.medicamento
                        ).first()
                        if canasta_ges:
                            cuotas_usadas = CuotaGES.objects.filter(
                                inscripcion=inscripcion_ges,
                                canasta=canasta_ges
                            ).count()
                            if cuotas_usadas >= canasta_ges.cuotas_autorizadas:
                                raise ValueError(
                                    f'El paciente ya retiró el total de cuotas autorizadas '
                                    f'({canasta_ges.cuotas_autorizadas}/{canasta_ges.cuotas_autorizadas}) '
                                    f'para {detalle.medicamento.nombre_generico} en este período.'
                                )
                            prox_numero_cuota = cuotas_usadas + 1

                    # Verificar regla de vencimiento más próximo (FEFO)
                    lotes_fefo = detalle.medicamento.lotes_fefo()
                    lote_fefo_sugerido = lotes_fefo.first()
                    es_override = (
                        lote_fefo_sugerido is not None
                        and lote.pk != lote_fefo_sugerido.pk
                        and lote.fecha_vencimiento >= lote_fefo_sugerido.fecha_vencimiento
                    )
                    justificacion = request.POST.get(f'justificacion_{detalle.id}', '').strip()

                    if es_override and not justificacion:
                        raise ValueError(
                            f'Debe ingresar una justificación técnica para entregar el lote {lote.numero_lote} '
                            f'en lugar del lote con vencimiento más próximo ({lote_fefo_sugerido.numero_lote}).'
                        )

                    # Si la receta contiene un controlado y no ha sido autorizada por Q.F., impedir entrega por Técnico
                    if (detalle.medicamento.es_controlado or receta.es_controlada) and request.user.rol == 'tecnico' and not receta.autorizada_qf:
                        raise ValueError(
                            f'La entrega de {detalle.medicamento.nombre_generico} (medicamento controlado) '
                            f'requiere autorización previa del Químico Farmacéutico.'
                        )

                    operaciones_preparadas.append({
                        'detalle': detalle,
                        'lote': lote,
                        'cantidad': cantidad,
                        'es_override': es_override,
                        'justificacion': justificacion,
                        'lote_fefo_sugerido': lote_fefo_sugerido,
                        'inscripcion_ges': inscripcion_ges,
                        'canasta_ges': canasta_ges,
                        'prox_numero_cuota': prox_numero_cuota,
                    })

                if not operaciones_preparadas:
                    raise ValueError('Debe indicar una cantidad mayor a cero en al menos un medicamento para registrar la entrega.')

                # Crear cabecera de Dispensación
                dispensacion = Dispensacion.objects.create(
                    receta=receta,
                    usuario_dispensador=request.user,
                    retiro_tercero=retiro_tercero,
                    tercero_autorizado=tercero,
                    copago=0,
                    observaciones=request.POST.get('observaciones', '').strip(),
                )

                # Ejecutar descuentos de inventario, movimientos, cuotas GES y libro de controlados
                resumen_stock = []
                for op in operaciones_preparadas:
                    detalle = op['detalle']
                    lote = op['lote']
                    cantidad = op['cantidad']
                    es_override = op['es_override']
                    justificacion = op['justificacion']
                    lote_fefo_sugerido = op['lote_fefo_sugerido']

                    DetalleDispensacion.objects.create(
                        dispensacion=dispensacion,
                        detalle_receta=detalle,
                        lote=lote,
                        cantidad=cantidad,
                        fefo_override=es_override,
                        justificacion_override=justificacion if es_override else '',
                    )

                    cantidad_anterior = lote.cantidad_actual
                    lote.cantidad_actual -= cantidad
                    lote.save()
                    resumen_stock.append(
                        f'{lote.numero_lote}: {cantidad_anterior} → {lote.cantidad_actual} unid. (-{cantidad})'
                    )

                    detalle.cantidad_dispensada += cantidad
                    detalle.save()

                    MovimientoStock.objects.create(
                        lote=lote,
                        tipo=MovimientoStock.TipoMovimiento.EGRESO_DISPENSACION,
                        cantidad=-cantidad,
                        cantidad_anterior=cantidad_anterior,
                        cantidad_posterior=lote.cantidad_actual,
                        motivo=f'Entrega de receta {receta.numero_receta}',
                        usuario=request.user,
                        ubicacion_origen=lote.ubicacion,
                    )

                    # Si corresponde a canasta GES activa, descontar cuota automáticamente
                    if op['inscripcion_ges'] and op['canasta_ges'] and op['prox_numero_cuota']:
                        CuotaGES.objects.get_or_create(
                            inscripcion=op['inscripcion_ges'],
                            canasta=op['canasta_ges'],
                            numero_cuota=op['prox_numero_cuota'],
                            defaults={
                                'cantidad_entregada': cantidad,
                                'dispensacion': dispensacion,
                            }
                        )

                    # Si es medicamento controlado, asentar automáticamente en el Libro de Controlados bajo Q.F. responsable
                    if detalle.medicamento.es_controlado:
                        qf_resp = request.user if request.user.rol == 'quimico' else (receta.qf_autorizador or request.user)
                        LibroControlados.objects.create(
                            folio=LibroControlados.siguiente_folio(),
                            medicamento=detalle.medicamento,
                            lote=lote,
                            tipo_movimiento=LibroControlados.TipoMovimiento.EGRESO,
                            cantidad=cantidad,
                            saldo_anterior=cantidad_anterior,
                            saldo_posterior=lote.cantidad_actual,
                            receta=receta,
                            paciente=receta.paciente,
                            quimico_responsable=qf_resp,
                            verificacion_2fa=True,
                            observaciones=f'Egreso por entrega de receta {receta.numero_receta}',
                        )

                    if es_override and lote_fefo_sugerido:
                        registrar_auditoria(
                            request.user,
                            'Cambio manual de lote sugerido en dispensación',
                            f'Medicamento: {detalle.medicamento.nombre_generico}',
                            valores_anteriores={'lote_sugerido_fefo': lote_fefo_sugerido.numero_lote},
                            valores_nuevos={
                                'lote_seleccionado': lote.numero_lote,
                                'justificacion': justificacion,
                            }
                        )

                # Actualizar estado y autorización Q.F. si quien dispensó directamente es el Q.F.
                todos_dispensados = all(d.completamente_dispensado for d in receta.detalles.all())
                receta.estado = (
                    Receta.EstadoReceta.DISPENSADA_TOTAL
                    if todos_dispensados
                    else Receta.EstadoReceta.DISPENSADA_PARCIAL
                )
                if receta.es_controlada and not receta.autorizada_qf and request.user.rol == 'quimico':
                    receta.autorizada_qf = True
                    receta.qf_autorizador = request.user
                    receta.fecha_autorizacion_qf = timezone.now()
                receta.save()

                registrar_auditoria(
                    request.user,
                    'Dispensación realizada',
                    f'Receta {receta.numero_receta}',
                    valores_nuevos={
                        'dispensacion_id': dispensacion.id,
                        'paciente': str(receta.paciente),
                        'retiro_tercero': retiro_tercero,
                        'tercero': str(tercero) if tercero else None,
                    }
                )

                resumen_txt = f' Stock actualizado: {" · ".join(resumen_stock)}.' if resumen_stock else ''
                messages.success(
                    request,
                    f'Entrega registrada correctamente para la receta {receta.numero_receta}.{resumen_txt}'
                )
                return redirect('dispensacion:dispensacion_detalle', pk=dispensacion.pk)

        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No fue posible completar la entrega: {e}')

    # GET: Preparar formulario con lotes ordenados por vencimiento
    detalles_info = []
    for detalle in detalles:
        lotes_fefo = detalle.medicamento.lotes_fefo()
        detalles_info.append({
            'detalle': detalle,
            'lotes_fefo': lotes_fefo,
            'lote_sugerido': lotes_fefo.first() if lotes_fefo.exists() else None,
            'cantidad_pendiente': detalle.cantidad_pendiente,
        })

    ctx_doc = _construir_contexto_documento_receta(receta, incluir_lotes=False)
    ctx_doc['detalles_info'] = detalles_info
    return render(request, 'dispensacion/dispensar_receta.html', ctx_doc)


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para consultar el historial de dispensaciones de pacientes.'
)
def historial(request):
    """Historial de dispensaciones realizadas (Técnico en Farmacia visualiza su propio historial de entregas)."""
    qs = Dispensacion.objects.all().select_related(
        'receta', 'receta__paciente', 'usuario_dispensador', 'tercero_autorizado'
    )
    if request.user.rol == 'tecnico' and request.GET.get('ver') != 'todas':
        qs = qs.filter(usuario_dispensador=request.user)
    dispensaciones = qs[:60]
    return render(request, 'dispensacion/historial.html', {
        'dispensaciones': dispensaciones,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para acceder a comprobantes de dispensación de pacientes.'
)
def dispensacion_detalle(request, pk):
    """Comprobante detallado de una entrega de medicamentos con impacto en inventario/Kardex."""
    dispensacion = get_object_or_404(
        Dispensacion.objects.select_related(
            'receta', 'receta__paciente', 'receta__medico',
            'usuario_dispensador', 'tercero_autorizado'
        ),
        pk=pk
    )
    detalles = list(
        dispensacion.detalles.all().select_related(
            'detalle_receta', 'detalle_receta__medicamento', 'lote', 'lote__ubicacion'
        )
    )
    motivo_esperado = f'Entrega de receta {dispensacion.receta.numero_receta}'
    impacto_stock = []
    for d in detalles:
        mov = (
            MovimientoStock.objects.filter(
                lote=d.lote,
                tipo=MovimientoStock.TipoMovimiento.EGRESO_DISPENSACION,
                motivo=motivo_esperado,
                cantidad=-d.cantidad,
            )
            .order_by('-fecha', '-id')
            .first()
        )
        stock_ant = mov.cantidad_anterior if mov else (d.lote.cantidad_actual + d.cantidad)
        stock_post = mov.cantidad_posterior if mov else d.lote.cantidad_actual
        med = d.detalle_receta.medicamento
        impacto_stock.append({
            'medicamento': med,
            'lote': d.lote,
            'cantidad_entregada': d.cantidad,
            'stock_anterior': stock_ant,
            'stock_posterior': stock_post,
            'stock_actual_lote': d.lote.cantidad_actual,
            'stock_total_med': med.stock_total,
            'en_quiebre': med.en_quiebre,
        })
    return render(request, 'dispensacion/dispensacion_detalle.html', {
        'dispensacion': dispensacion,
        'detalles': detalles,
        'impacto_stock': impacto_stock,
    })
