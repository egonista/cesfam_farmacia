"""
Vistas del módulo Carros Clínicos del Sistema CESFAM Farmacia.
Control estricto del ciclo de Carro de Paro y Carro Unidosis:
OPERATIVO -> Rotura de precinto por consumo -> INCOMPLETO_EN_REPOSICION -> Reposición con nuevo precinto -> OPERATIVO.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import CarroClinico, PlantillaItemCarro, ConsumoCarroClinico, ReposicionCarro
from farmacia.models import Medicamento, Lote, MovimientoStock
from core.utils import registrar_auditoria
from core.decorators import rol_requerido, denegar_acceso


@rol_requerido('admin', 'quimico', 'tecnico', 'clinico')
@transaction.atomic
def carro_list(request):
    """Lista de carros clínicos y creación de nuevos carros."""
    if request.method == 'POST':
        if request.user.rol not in ('admin', 'quimico'):
            return denegar_acceso(
                request,
                motivo='Solo el Administrador y el Químico Farmacéutico pueden dar de alta o configurar nuevos carros clínicos.',
                roles_autorizados=('admin', 'quimico')
            )
        try:
            nombre = request.POST.get('nombre', '').strip()
            tipo = request.POST.get('tipo', CarroClinico.TipoCarro.PARO)
            ubicacion = request.POST.get('ubicacion_fisica', '').strip()
            precinto = request.POST.get('numero_precinto', '').strip()
            if not nombre or not ubicacion:
                raise ValueError('Debe indicar el nombre y la ubicación física del carro clínico.')

            carro = CarroClinico.objects.create(
                nombre=nombre,
                tipo=tipo,
                ubicacion_fisica=ubicacion,
                estado=CarroClinico.EstadoCarro.SIN_DOTACION,
                numero_precinto=precinto,
                fecha_ultimo_precinto=timezone.now() if precinto else None,
                responsable_actual=request.user,
            )
            registrar_auditoria(
                request.user,
                'Alta de Carro Clínico',
                f'Carro: {carro.nombre}',
                valores_nuevos={'tipo': carro.tipo, 'ubicacion': carro.ubicacion_fisica, 'precinto': precinto}
            )
            messages.success(request, f'Carro "{carro.nombre}" creado correctamente.')
            return redirect('carros_clinicos:carro_detalle', pk=carro.pk)
        except Exception as e:
            messages.error(request, f'No fue posible crear el carro: {e}')

    carros = (
        CarroClinico.objects.filter(activo=True)
        .prefetch_related(
            'plantilla_items__medicamento__lotes',
            'plantilla_items__reposiciones__lote',
        )
    )
    return render(request, 'carros_clinicos/carro_list.html', {'carros': carros})


@rol_requerido('admin', 'quimico', 'tecnico', 'clinico')
@transaction.atomic
def carro_detalle(request, pk):
    """Detalle de un carro clínico con su dotación estandarizada."""
    carro = get_object_or_404(CarroClinico, pk=pk, activo=True)

    if request.method == 'POST':
        if request.user.rol not in ('admin', 'quimico'):
            return denegar_acceso(
                request,
                motivo='Solo el Administrador y el Químico Farmacéutico pueden modificar la composición base de carros clínicos.',
                roles_autorizados=('admin', 'quimico')
            )
        accion = request.POST.get('accion')
        if accion == 'agregar_item_plantilla':
            try:
                med = get_object_or_404(Medicamento, pk=request.POST.get('medicamento_id'))
                cant_req = int(request.POST.get('cantidad_requerida', 5) or 5)
                cant_act_raw = request.POST.get('cantidad_actual', '')
                cant_act = int(cant_act_raw) if str(cant_act_raw).strip() != '' else cant_req
                ubic_carro = request.POST.get('ubicacion_en_carro', 'Cajón Principal').strip() or 'Cajón Principal'

                if cant_req <= 0:
                    raise ValueError('La cantidad requerida debe ser mayor a cero.')
                if cant_act < 0 or cant_act > cant_req:
                    raise ValueError('La cantidad actual inicial debe estar entre 0 y la cantidad requerida.')

                item_p, created = PlantillaItemCarro.objects.get_or_create(
                    carro=carro,
                    medicamento=med,
                    defaults={
                        'cantidad_requerida': cant_req,
                        'cantidad_actual': cant_act,
                        'ubicacion_en_carro': ubic_carro,
                    }
                )
                if not created:
                    item_p.cantidad_requerida = cant_req
                    item_p.cantidad_actual = cant_act
                    item_p.ubicacion_en_carro = ubic_carro
                    item_p.save()

                lote_fefo = med.lotes_fefo().first()
                carro.estado = (
                    CarroClinico.EstadoCarro.COMPLETO
                    if carro.esta_completo
                    else CarroClinico.EstadoCarro.INCOMPLETO
                )
                carro.save(update_fields=['estado'])

                registrar_auditoria(
                    request.user,
                    'Alta de Ítem en Plantilla de Carro' if created else 'Actualización de Ítem en Plantilla de Carro',
                    f'{carro.nombre} — {med.nombre_generico}',
                    valores_nuevos={
                        'ubicacion_en_carro': ubic_carro,
                        'cantidad_requerida': cant_req,
                        'cantidad_actual': cant_act,
                        'lote_fefo_asignado': lote_fefo.numero_lote if lote_fefo else None,
                    }
                )
                lote_txt = f' (Lote FEFO asignado: {lote_fefo.numero_lote})' if lote_fefo else ' (sin stock FEFO vigente en farmacia)'
                messages.success(request, f'Ítem {med.nombre_generico} guardado en la plantilla del carro{lote_txt}.')
            except Exception as e:
                messages.error(request, f'No se pudo actualizar la dotación: {e}')
            return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    items = carro.plantilla_items.all().select_related('medicamento').prefetch_related(
        'medicamento__lotes',
        'reposiciones__lote',
    )
    items_con_lote = []
    items_faltantes = []
    tiene_lote_alerta_60 = False
    for it in items:
        lote_ref = it.lote_referencia
        dias_vencer = lote_ref.dias_para_vencer if lote_ref else None
        if dias_vencer is not None and dias_vencer <= 60:
            tiene_lote_alerta_60 = True
        lotes_fefo_med = list(it.medicamento.lotes_fefo())
        items_con_lote.append({
            'item': it,
            'lote_ref': lote_ref,
            'dias_vencer': dias_vencer,
            'lotes_fefo': lotes_fefo_med,
        })
        if it.faltante > 0:
            items_faltantes.append(it)

    consumos_qs = carro.consumos.all().select_related('item__medicamento', 'personal_clinico').order_by('-fecha')
    if request.user.rol == 'clinico':
        consumos_qs = consumos_qs.filter(personal_clinico=request.user)
    consumos_recientes = consumos_qs[:20]
    reposiciones_recientes = carro.reposiciones.all().select_related('item__medicamento', 'lote', 'usuario_farmacia').order_by('-fecha')[:20]
    todos_medicamentos = Medicamento.objects.filter(activo=True).order_by('nombre_generico')

    return render(request, 'carros_clinicos/carro_detalle.html', {
        'carro': carro,
        'items': items,
        'items_con_lote': items_con_lote,
        'items_faltantes': items_faltantes,
        'tiene_lote_alerta_60': tiene_lote_alerta_60,
        'consumos_recientes': consumos_recientes,
        'reposiciones_recientes': reposiciones_recientes,
        'todos_medicamentos': todos_medicamentos,
        'tipos_carro': CarroClinico.TipoCarro.choices,
        'tiene_historial': carro.tiene_historial_operativo,
    })


@rol_requerido(
    'admin', 'quimico',
    motivo='Solo el Administrador y el Químico Farmacéutico pueden editar los datos básicos de un carro clínico.'
)
@transaction.atomic
def carro_editar(request, pk):
    """Edita nombre, tipo y ubicación física de un carro clínico."""
    carro = get_object_or_404(CarroClinico, pk=pk, activo=True)
    if request.method != 'POST':
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    nombre = request.POST.get('nombre', '').strip()
    tipo = request.POST.get('tipo', carro.tipo).strip()
    ubicacion = request.POST.get('ubicacion_fisica', '').strip()

    if not nombre or not ubicacion:
        messages.error(request, 'Debe ingresar el nombre y la ubicación física del carro.')
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    tipos_validos = {c[0] for c in CarroClinico.TipoCarro.choices}
    if tipo not in tipos_validos:
        tipo = carro.tipo

    anteriores = {
        'nombre': carro.nombre,
        'tipo': carro.tipo,
        'ubicacion_fisica': carro.ubicacion_fisica,
    }
    carro.nombre = nombre
    carro.tipo = tipo
    carro.ubicacion_fisica = ubicacion
    carro.save(update_fields=['nombre', 'tipo', 'ubicacion_fisica', 'fecha_modificacion'])

    registrar_auditoria(
        request.user,
        'Edición de Datos de Carro Clínico',
        f'Carro: {carro.nombre}',
        valores_anteriores=anteriores,
        valores_nuevos={
            'nombre': carro.nombre,
            'tipo': carro.tipo,
            'ubicacion_fisica': carro.ubicacion_fisica,
        },
    )
    messages.success(request, f'Datos del carro "{carro.nombre}" actualizados correctamente.')
    return redirect('carros_clinicos:carro_detalle', pk=carro.pk)


@rol_requerido(
    'admin',
    motivo='Solo el Administrador (Docente) está autorizado para eliminar o desactivar un carro clínico.'
)
@transaction.atomic
def carro_eliminar(request, pk):
    """
    Elimina un carro clínico si no posee consumos/reposiciones históricas.
    Si tiene historial operativo, impide la eliminación física y permite desactivarlo.
    """
    carro = get_object_or_404(CarroClinico, pk=pk, activo=True)
    if request.method != 'POST':
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    accion_borrado = request.POST.get('modo', 'eliminar').strip()
    tiene_historial = carro.tiene_historial_operativo
    nombre = carro.nombre

    if tiene_historial and accion_borrado != 'desactivar':
        messages.error(
            request,
            f'No es posible eliminar físicamente "{nombre}" porque posee historial de consumos o reposiciones. '
            f'Utiliza la opción "Desactivar Carro" para conservar la trazabilidad clínica.'
        )
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    if tiene_historial or accion_borrado == 'desactivar':
        carro.activo = False
        carro.save(update_fields=['activo', 'fecha_modificacion'])
        registrar_auditoria(
            request.user,
            'Desactivación de Carro Clínico',
            f'Carro: {nombre}',
            valores_anteriores={'activo': True},
            valores_nuevos={'activo': False, 'con_historial': tiene_historial},
        )
        messages.success(request, f'Carro "{nombre}" desactivado correctamente (se conserva su historial de auditoría).')
        return redirect('carros_clinicos:carro_list')

    carro.plantilla_items.all().delete()
    carro.delete()
    registrar_auditoria(
        request.user,
        'Eliminación de Carro Clínico',
        f'Carro: {nombre}',
        valores_anteriores={'nombre': nombre},
        valores_nuevos={'eliminado': True},
    )
    messages.success(request, f'Carro "{nombre}" eliminado correctamente.')
    return redirect('carros_clinicos:carro_list')


@rol_requerido(
    'admin', 'quimico',
    motivo='Solo el Administrador y el Químico Farmacéutico pueden editar ítems de la plantilla canónica de un carro.'
)
@transaction.atomic
def item_plantilla_editar(request, pk, item_pk):
    """Edita la cantidad requerida y ubicación en cajón de un ítem de la plantilla del carro."""
    carro = get_object_or_404(CarroClinico, pk=pk, activo=True)
    item = get_object_or_404(PlantillaItemCarro.objects.select_related('medicamento'), pk=item_pk, carro=carro)
    if request.method != 'POST':
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    try:
        nueva_req = int(request.POST.get('cantidad_requerida', item.cantidad_requerida) or 0)
        if nueva_req <= 0:
            raise ValueError('La cantidad requerida debe ser mayor a cero.')
        nueva_ubic = request.POST.get('ubicacion_en_carro', item.ubicacion_en_carro).strip() or item.ubicacion_en_carro

        anteriores = {
            'cantidad_requerida': item.cantidad_requerida,
            'ubicacion_en_carro': item.ubicacion_en_carro,
        }
        item.cantidad_requerida = nueva_req
        item.ubicacion_en_carro = nueva_ubic
        item.save(update_fields=['cantidad_requerida', 'ubicacion_en_carro'])

        carro.estado = (
            CarroClinico.EstadoCarro.COMPLETO
            if carro.esta_completo
            else CarroClinico.EstadoCarro.INCOMPLETO
        )
        carro.save(update_fields=['estado'])

        registrar_auditoria(
            request.user,
            'Edición de Ítem en Plantilla de Carro',
            f'{carro.nombre} — {item.medicamento.nombre_generico}',
            valores_anteriores=anteriores,
            valores_nuevos={
                'cantidad_requerida': item.cantidad_requerida,
                'ubicacion_en_carro': item.ubicacion_en_carro,
                'estado_carro': carro.estado,
            },
        )
        messages.success(
            request,
            f'Plantilla de {item.medicamento.nombre_generico} actualizada (Requerido: {item.cantidad_requerida}).'
        )
    except ValueError as ve:
        messages.error(request, str(ve))
    except Exception as e:
        messages.error(request, f'No fue posible editar el ítem: {e}')

    return redirect('carros_clinicos:carro_detalle', pk=carro.pk)


@rol_requerido(
    'admin', 'quimico',
    motivo='Solo el Administrador y el Químico Farmacéutico pueden quitar ítems de la plantilla canónica de un carro.'
)
@transaction.atomic
def item_plantilla_eliminar(request, pk, item_pk):
    """Quita un ítem de la plantilla canónica del carro si no tiene historial protegido."""
    carro = get_object_or_404(CarroClinico, pk=pk, activo=True)
    item = get_object_or_404(PlantillaItemCarro.objects.select_related('medicamento'), pk=item_pk, carro=carro)
    if request.method != 'POST':
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    if item.consumos.exists() or item.reposiciones.exists():
        messages.error(
            request,
            f'No es posible quitar {item.medicamento.nombre_generico} porque posee consumos o reposiciones históricas registradas.'
        )
        return redirect('carros_clinicos:carro_detalle', pk=carro.pk)

    med_nombre = item.medicamento.nombre_generico
    item.delete()

    if not carro.plantilla_items.exists():
        carro.estado = CarroClinico.EstadoCarro.SIN_DOTACION
    elif carro.esta_completo:
        carro.estado = CarroClinico.EstadoCarro.COMPLETO
    else:
        carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
    carro.save(update_fields=['estado'])

    registrar_auditoria(
        request.user,
        'Eliminación de Ítem de Plantilla de Carro',
        f'{carro.nombre} — {med_nombre}',
        valores_anteriores={'medicamento': med_nombre},
        valores_nuevos={'estado_carro': carro.estado},
    )
    messages.success(request, f'{med_nombre} fue quitado de la plantilla del carro.')
    return redirect('carros_clinicos:carro_detalle', pk=carro.pk)


@rol_requerido(
    'clinico', 'quimico',
    motivo='Solo el Personal Clínico (o supervisión farmacéutica) puede registrar consumos clínicos en Carro de Paro y Carro Unidosis. El Administrador no puede registrar consumos.'
)
@transaction.atomic
def registrar_consumo(request, pk):
    """
    Registrar consumo de emergencia en el carro clínico (rotura de precinto).
    Cambia inmediatamente el estado del carro a Incompleto - En Reposición.
    """
    if request.method == 'POST':
        try:
            with transaction.atomic():
                carro = get_object_or_404(CarroClinico.objects.select_for_update(), pk=pk)
                item = get_object_or_404(
                    PlantillaItemCarro.objects.select_for_update().select_related('medicamento'),
                    pk=request.POST.get('item'),
                    carro=carro
                )
                cantidad = int(request.POST.get('cantidad', 0) or 0)
                motivo = request.POST.get('motivo', '').strip()

                if cantidad <= 0:
                    raise ValueError('La cantidad consumida debe ser mayor a cero.')
                if cantidad > item.cantidad_actual:
                    raise ValueError(
                        f'La cantidad indicada ({cantidad}) supera las unidades disponibles en el carro ({item.cantidad_actual}).'
                    )
                if not motivo:
                    raise ValueError('Debe indicar el motivo clínico de la atención o emergencia.')

                ConsumoCarroClinico.objects.create(
                    carro=carro,
                    item=item,
                    cantidad_consumida=cantidad,
                    motivo=motivo,
                    paciente_atendido=request.POST.get('paciente_atendido', '').strip(),
                    personal_clinico=request.user,
                )

                item.cantidad_actual -= cantidad
                item.save()

                # Al abrirse el carro y registrarse consumo, pasa inmediatamente a Incompleto - En Reposición
                estado_anterior = carro.estado
                carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
                carro.save()

                registrar_auditoria(
                    request.user,
                    'Consumo de urgencia y apertura de precinto en carro clínico',
                    f'Carro: {carro.nombre}',
                    valores_anteriores={'estado': estado_anterior, 'precinto': carro.numero_precinto},
                    valores_nuevos={
                        'estado': carro.estado,
                        'medicamento': item.medicamento.nombre_generico,
                        'cantidad_consumida': cantidad,
                        'motivo': motivo,
                    }
                )

                messages.warning(
                    request,
                    f'Consumo registrado ({item.medicamento.nombre_generico} x{cantidad}). '
                    f'El carro quedó en estado "Incompleto - En Reposición".'
                )
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No fue posible registrar el consumo: {e}')

    return redirect('carros_clinicos:carro_detalle', pk=pk)


@rol_requerido(
    'tecnico', 'quimico',
    motivo='Solo el Técnico en Farmacia y el Químico Farmacéutico pueden ejecutar la reposición física y nuevo sellado de Carros Clínicos.'
)
@transaction.atomic
def reponer_carro(request, pk):
    """
    Reponer medicamentos del carro clínico desde farmacia y sellar con nuevo precinto.
    Restaura el estado Completo - Operativo cuando la dotación está al 100%.
    """
    if request.method == 'POST':
        try:
            with transaction.atomic():
                carro = get_object_or_404(CarroClinico.objects.select_for_update(), pk=pk)
                item = get_object_or_404(
                    PlantillaItemCarro.objects.select_for_update().select_related('medicamento'),
                    pk=request.POST.get('item'),
                    carro=carro
                )
                lote = get_object_or_404(
                    Lote.objects.select_for_update().select_related('medicamento'),
                    pk=request.POST.get('lote')
                )
                cantidad = int(request.POST.get('cantidad', 0) or 0)
                nuevo_precinto = request.POST.get('nuevo_precinto', '').strip()

                if cantidad <= 0:
                    raise ValueError('La cantidad a reponer debe ser mayor a cero.')
                if item.cantidad_actual + cantidad > item.cantidad_requerida:
                    raise ValueError(
                        f'La cantidad a reponer ({cantidad}) excede el faltante del ítem en el carro '
                        f'(Actual: {item.cantidad_actual} / Requerido: {item.cantidad_requerida} · Faltante: {item.faltante}).'
                    )
                if not nuevo_precinto:
                    raise ValueError('Debe ingresar el número del nuevo precinto de seguridad instalado.')
                if lote.medicamento_id != item.medicamento_id:
                    raise ValueError(
                        f'El lote seleccionado pertenece a {lote.medicamento.nombre_generico} y no coincide con '
                        f'el ítem a reponer ({item.medicamento.nombre_generico}).'
                    )
                if lote.en_cuarentena or not lote.activo:
                    raise ValueError(f'El lote {lote.numero_lote} se encuentra inactivo o en cuarentena.')
                if lote.esta_vencido:
                    raise ValueError(f'El lote {lote.numero_lote} está vencido y no puede asignarse al carro clínico.')
                if cantidad > lote.cantidad_actual:
                    raise ValueError(f'Stock insuficiente en el lote {lote.numero_lote} ({lote.cantidad_actual} disponibles).')

                cantidad_anterior = lote.cantidad_actual
                lote.cantidad_actual -= cantidad
                lote.save()

                item.cantidad_actual += cantidad
                item.save()

                MovimientoStock.objects.create(
                    lote=lote,
                    tipo=MovimientoStock.TipoMovimiento.EGRESO_CARRO,
                    cantidad=-cantidad,
                    cantidad_anterior=cantidad_anterior,
                    cantidad_posterior=lote.cantidad_actual,
                    motivo=f'Reposición de {carro.nombre} (Precinto {nuevo_precinto})',
                    usuario=request.user,
                    ubicacion_origen=lote.ubicacion,
                )

                ReposicionCarro.objects.create(
                    carro=carro,
                    item=item,
                    lote=lote,
                    cantidad_repuesta=cantidad,
                    usuario_farmacia=request.user,
                    nuevo_precinto=nuevo_precinto,
                )

                precinto_anterior = carro.numero_precinto
                carro.numero_precinto = nuevo_precinto
                carro.fecha_ultimo_precinto = timezone.now()

                if carro.esta_completo:
                    carro.estado = CarroClinico.EstadoCarro.COMPLETO
                else:
                    carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
                carro.save()

                registrar_auditoria(
                    request.user,
                    'Reposición y sellado de carro clínico',
                    f'Carro: {carro.nombre}',
                    valores_anteriores={'precinto': precinto_anterior},
                    valores_nuevos={
                        'medicamento': item.medicamento.nombre_generico,
                        'cantidad_repuesta': cantidad,
                        'lote': lote.numero_lote,
                        'nuevo_precinto': nuevo_precinto,
                        'estado': carro.estado,
                    }
                )

                messages.success(
                    request,
                    f'Reposición completada ({item.medicamento.nombre_generico} +{cantidad}). '
                    f'Nuevo precinto registrado: {nuevo_precinto}.'
                )
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No fue posible completar la reposición: {e}')

    return redirect('carros_clinicos:carro_detalle', pk=pk)
