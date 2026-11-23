"""
Vistas del módulo Dispensación del Sistema CESFAM Farmacia.
Lógica FEFO, dispensación gratuita, tercero autorizado.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.db.models import Q, F
from django.shortcuts import render, redirect, get_object_or_404

from .models import Receta, DetalleReceta, Dispensacion, DetalleDispensacion, TerceroAutorizado
from core.models import Paciente, MedicoPrescriptor
from core.utils import validar_rut, formatear_rut, registrar_auditoria
from farmacia.models import Medicamento, Lote, MovimientoStock


@login_required
def receta_list(request):
    """Lista de recetas con búsqueda."""
    query = request.GET.get('q', '')
    estado = request.GET.get('estado', '')

    recetas = Receta.objects.all().select_related('paciente', 'medico')
    if query:
        recetas = recetas.filter(
            Q(numero_receta__icontains=query) |
            Q(paciente__rut__icontains=query) |
            Q(paciente__apellido_paterno__icontains=query)
        )
    if estado:
        recetas = recetas.filter(estado=estado)

    return render(request, 'dispensacion/receta_list.html', {
        'recetas': recetas[:50],
        'query': query,
        'estado': estado,
        'estados': Receta.EstadoReceta.choices,
    })


@login_required
def receta_crear(request):
    """Crear una nueva receta médica."""
    if request.method == 'POST':
        try:
            paciente = Paciente.objects.get(pk=request.POST.get('paciente'))
            medico = MedicoPrescriptor.objects.get(pk=request.POST.get('medico'))

            if not medico.habilitado:
                messages.error(request, 'El médico prescriptor no está habilitado.')
                return redirect('dispensacion:receta_crear')

            receta = Receta.objects.create(
                numero_receta=request.POST.get('numero_receta'),
                paciente=paciente,
                medico=medico,
                tipo=request.POST.get('tipo', 'simple'),
                diagnostico=request.POST.get('diagnostico', ''),
                fecha_emision=request.POST.get('fecha_emision'),
                fecha_vencimiento=request.POST.get('fecha_vencimiento'),
                observaciones=request.POST.get('observaciones', ''),
            )

            # Procesar detalles de medicamentos
            medicamento_ids = request.POST.getlist('medicamento_id')
            cantidades = request.POST.getlist('cantidad')
            posologias = request.POST.getlist('posologia')
            dias_trat = request.POST.getlist('dias_tratamiento')

            for i in range(len(medicamento_ids)):
                if medicamento_ids[i]:
                    DetalleReceta.objects.create(
                        receta=receta,
                        medicamento_id=int(medicamento_ids[i]),
                        cantidad_prescrita=int(cantidades[i]) if i < len(cantidades) else 1,
                        posologia=posologias[i] if i < len(posologias) else '',
                        dias_tratamiento=int(dias_trat[i]) if i < len(dias_trat) else 30,
                    )

            messages.success(request, f'Receta {receta.numero_receta} creada exitosamente.')
            return redirect('dispensacion:receta_detalle', pk=receta.pk)
        except Exception as e:
            messages.error(request, f'Error al crear receta: {e}')

    pacientes = Paciente.objects.filter(activo=True)
    medicos = MedicoPrescriptor.objects.filter(habilitado=True)
    medicamentos = Medicamento.objects.filter(activo=True)

    return render(request, 'dispensacion/receta_form.html', {
        'pacientes': pacientes,
        'medicos': medicos,
        'medicamentos': medicamentos,
        'tipos_receta': Receta.TipoReceta.choices,
    })


@login_required
@transaction.atomic
def receta_detalle(request, pk):
    """Detalle de receta con lotes FEFO disponibles y edición de ítems antes de dispensar."""
    receta = get_object_or_404(Receta, pk=pk)

    if request.method == 'POST' and receta.estado in ('pendiente', 'parcial', 'anulada'):
        accion = request.POST.get('accion')
        if accion == 'agregar_medicamento_receta':
            med = get_object_or_404(Medicamento, pk=request.POST.get('medicamento_id'))
            cant = int(request.POST.get('cantidad_prescrita', 30) or 30)
            posologia = request.POST.get('posologia', '1 comprimido cada 12 horas').strip()
            dias = int(request.POST.get('dias_tratamiento', 30) or 30)
            DetalleReceta.objects.create(
                receta=receta,
                medicamento=med,
                cantidad_prescrita=cant,
                posologia=posologia,
                dias_tratamiento=dias,
            )
            registrar_auditoria(
                request.user,
                'Adición de Medicamento a Receta Médica',
                f'Receta {receta.numero_receta}',
                valores_nuevos={'medicamento': med.nombre_generico, 'cantidad': cant}
            )
            messages.success(request, f'Se agregó {med.nombre_generico} ({cant} unid.) a la receta.')
            return redirect('dispensacion:receta_detalle', pk=receta.pk)

        elif accion == 'eliminar_detalle_receta':
            det = get_object_or_404(DetalleReceta, pk=request.POST.get('detalle_id'), receta=receta)
            if det.cantidad_dispensada == 0:
                nombre_m = det.medicamento.nombre_generico
                det.delete()
                messages.warning(request, f'Se quitó {nombre_m} de la receta.')
            else:
                messages.error(request, 'No se puede quitar un ítem que ya registra entregas.')
            return redirect('dispensacion:receta_detalle', pk=receta.pk)

        elif accion == 'anular_receta':
            receta.estado = Receta.EstadoReceta.ANULADA
            receta.save()
            registrar_auditoria(
                request.user,
                'Anulación de Receta Médica',
                f'Receta {receta.numero_receta}',
                valores_nuevos={'estado': 'anulada'}
            )
            messages.warning(request, f'Receta {receta.numero_receta} fue anulada.')
            return redirect('dispensacion:receta_detalle', pk=receta.pk)

        elif accion == 'reactivar_receta':
            receta.estado = Receta.EstadoReceta.PENDIENTE
            receta.save()
            messages.info(request, f'Receta {receta.numero_receta} reactivada como Pendiente.')
            return redirect('dispensacion:receta_detalle', pk=receta.pk)

    detalles = receta.detalles.all().select_related('medicamento')

    # Para cada detalle, obtener lotes FEFO disponibles
    detalles_con_lotes = []
    for detalle in detalles:
        lotes_fefo = detalle.medicamento.lotes_fefo()
        lote_sugerido = lotes_fefo.first() if lotes_fefo.exists() else None
        detalles_con_lotes.append({
            'detalle': detalle,
            'lotes_fefo': lotes_fefo,
            'lote_sugerido': lote_sugerido,
        })

    todos_medicamentos = Medicamento.objects.filter(activo=True).order_by('nombre_generico')

    return render(request, 'dispensacion/receta_detalle.html', {
        'receta': receta,
        'detalles_con_lotes': detalles_con_lotes,
        'todos_medicamentos': todos_medicamentos,
    })


@login_required
def dispensar(request):
    """Selección de receta pendiente para dispensar."""
    recetas_pendientes = Receta.objects.filter(
        estado__in=['pendiente', 'parcial']
    ).select_related('paciente', 'medico').order_by('-fecha_emision')

    return render(request, 'dispensacion/dispensar.html', {
        'recetas_pendientes': recetas_pendientes,
    })


@login_required
@transaction.atomic
def dispensar_receta(request, receta_pk):
    """
    Proceso completo de dispensación con lógica FEFO.
    - Valida vigencia de receta
    - Ordena lotes FEFO y preselecciona el más próximo a vencer
    - Permite override FEFO con justificación técnica obligatoria
    - Soporta retiro por tercero autorizado
    - Registra auditoría en MongoDB
    """
    receta = get_object_or_404(Receta, pk=receta_pk)

    if not receta.esta_vigente:
        messages.error(request, 'La receta ha vencido o está anulada. No se puede dispensar.')
        return redirect('dispensacion:receta_detalle', pk=receta.pk)

    if not request.user.tiene_permiso_dispensacion():
        messages.error(request, 'No tiene permisos para dispensar.')
        return redirect('dispensacion:dispensar')

    detalles = receta.detalles.filter(cantidad_dispensada__lt=models.F('cantidad_prescrita'))

    if request.method == 'POST':
        try:
            # Crear dispensación
            retiro_tercero = request.POST.get('retiro_tercero') == 'on'
            tercero = None

            if retiro_tercero:
                rut_tercero = request.POST.get('rut_tercero', '')
                if not validar_rut(rut_tercero):
                    messages.error(request, 'El RUT del tercero autorizado no es válido (Módulo 11).')
                    return redirect('dispensacion:dispensar_receta', receta_pk=receta.pk)

                tercero = TerceroAutorizado.objects.create(
                    rut=formatear_rut(rut_tercero),
                    nombres=request.POST.get('nombres_tercero', ''),
                    apellido_paterno=request.POST.get('ap_paterno_tercero', ''),
                    apellido_materno=request.POST.get('ap_materno_tercero', ''),
                    parentesco=request.POST.get('parentesco_tercero', ''),
                    telefono=request.POST.get('telefono_tercero', ''),
                )

            dispensacion = Dispensacion.objects.create(
                receta=receta,
                usuario_dispensador=request.user,
                retiro_tercero=retiro_tercero,
                tercero_autorizado=tercero,
                copago=0,
                observaciones=request.POST.get('observaciones', ''),
            )

            # Procesar cada detalle
            for detalle in detalles:
                lote_id = request.POST.get(f'lote_{detalle.id}')
                cantidad_str = request.POST.get(f'cantidad_{detalle.id}', '0')
                cantidad = int(cantidad_str) if cantidad_str else 0

                if cantidad <= 0 or not lote_id:
                    continue

                lote = Lote.objects.select_for_update().get(pk=lote_id)

                # Verificar si el lote puede dispensarse
                if not lote.puede_dispensar(detalle.dias_tratamiento):
                    messages.warning(
                        request,
                        f'Lote {lote.numero_lote} no puede dispensarse '
                        f'(vencido o vida útil insuficiente para {detalle.dias_tratamiento} días).'
                    )
                    continue

                if cantidad > lote.cantidad_actual:
                    messages.warning(
                        request,
                        f'Stock insuficiente en lote {lote.numero_lote}. '
                        f'Disponible: {lote.cantidad_actual}, solicitado: {cantidad}.'
                    )
                    continue

                # Verificar FEFO override
                lotes_fefo = detalle.medicamento.lotes_fefo(ubicacion=lote.ubicacion)
                lote_fefo_sugerido = lotes_fefo.first()
                es_override = lote_fefo_sugerido and lote.pk != lote_fefo_sugerido.pk
                justificacion = request.POST.get(f'justificacion_{detalle.id}', '')

                if es_override and not justificacion:
                    messages.error(
                        request,
                        f'Justificación técnica obligatoria al seleccionar un lote distinto al FEFO '
                        f'para {detalle.medicamento.nombre_generico}.'
                    )
                    continue

                # Crear detalle de dispensación
                DetalleDispensacion.objects.create(
                    dispensacion=dispensacion,
                    detalle_receta=detalle,
                    lote=lote,
                    cantidad=cantidad,
                    fefo_override=es_override,
                    justificacion_override=justificacion if es_override else '',
                )

                # Descontar stock
                cantidad_anterior = lote.cantidad_actual
                lote.cantidad_actual -= cantidad
                lote.save()

                # Actualizar detalle de receta
                detalle.cantidad_dispensada += cantidad
                detalle.save()

                # Registrar movimiento de stock
                MovimientoStock.objects.create(
                    lote=lote,
                    tipo=MovimientoStock.TipoMovimiento.EGRESO_DISPENSACION,
                    cantidad=-cantidad,
                    cantidad_anterior=cantidad_anterior,
                    cantidad_posterior=lote.cantidad_actual,
                    motivo=f'Dispensación receta {receta.numero_receta}',
                    usuario=request.user,
                    ubicacion_origen=lote.ubicacion,
                )

                # Registrar auditoría en MongoDB (FEFO override)
                if es_override:
                    registrar_auditoria(
                        request.user,
                        'Override FEFO en dispensación',
                        f'Medicamento: {detalle.medicamento.nombre_generico}',
                        valores_anteriores={'lote_sugerido_fefo': lote_fefo_sugerido.numero_lote},
                        valores_nuevos={
                            'lote_seleccionado': lote.numero_lote,
                            'justificacion': justificacion,
                        }
                    )

            # Actualizar estado de la receta
            todos_dispensados = all(d.completamente_dispensado for d in receta.detalles.all())
            if todos_dispensados:
                receta.estado = Receta.EstadoReceta.DISPENSADA_TOTAL
            else:
                receta.estado = Receta.EstadoReceta.DISPENSADA_PARCIAL
            receta.save()

            # Auditoría general de la dispensación
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

            messages.success(request, f'Dispensación completada para receta {receta.numero_receta}.')
            return redirect('dispensacion:dispensacion_detalle', pk=dispensacion.pk)

        except Exception as e:
            messages.error(request, f'Error en la dispensación: {e}')

    # GET: Preparar formulario con lotes FEFO
    detalles_info = []
    for detalle in detalles:
        lotes_fefo = detalle.medicamento.lotes_fefo()
        detalles_info.append({
            'detalle': detalle,
            'lotes_fefo': lotes_fefo,
            'lote_sugerido': lotes_fefo.first() if lotes_fefo.exists() else None,
            'cantidad_pendiente': detalle.cantidad_pendiente,
        })

    return render(request, 'dispensacion/dispensar_receta.html', {
        'receta': receta,
        'detalles_info': detalles_info,
    })


@login_required
def historial(request):
    """Historial de dispensaciones."""
    dispensaciones = Dispensacion.objects.all().select_related(
        'receta', 'receta__paciente', 'usuario_dispensador'
    )[:50]
    return render(request, 'dispensacion/historial.html', {
        'dispensaciones': dispensaciones,
    })


@login_required
def dispensacion_detalle(request, pk):
    """Detalle de una dispensación con todos los lotes dispensados."""
    dispensacion = get_object_or_404(
        Dispensacion.objects.select_related(
            'receta', 'receta__paciente', 'receta__medico',
            'usuario_dispensador', 'tercero_autorizado'
        ),
        pk=pk
    )
    detalles = dispensacion.detalles.all().select_related(
        'detalle_receta', 'detalle_receta__medicamento', 'lote'
    )
    return render(request, 'dispensacion/dispensacion_detalle.html', {
        'dispensacion': dispensacion,
        'detalles': detalles,
    })


# Necesario para el import de models.F en dispensar_receta
from django.db import models
