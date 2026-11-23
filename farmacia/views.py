"""
Vistas del módulo Farmacia del Sistema CESFAM.
Gestión de medicamentos, lotes, movimientos y alertas FEFO.
"""
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import (
    Medicamento, Lote, Ubicacion, MovimientoStock, CategoriaMedicamento,
    OrdenAbastecimiento, DetalleOrdenAbastecimiento
)
from core.utils import registrar_auditoria


@login_required
def medicamento_list(request):
    """Lista de medicamentos con búsqueda, filtros y creación (RF-03)."""
    if request.method == 'POST' and request.user.rol in ('admin', 'quimico'):
        try:
            cat = CategoriaMedicamento.objects.get(pk=request.POST.get('categoria'))
            es_ctrl = request.POST.get('es_controlado') == 'on' or cat.es_controlado
            med = Medicamento.objects.create(
                codigo=request.POST.get('codigo', '').strip().upper(),
                nombre_generico=request.POST.get('nombre_generico', '').strip(),
                nombre_comercial=request.POST.get('nombre_comercial', '').strip(),
                concentracion=request.POST.get('concentracion', '').strip(),
                forma_farmaceutica=request.POST.get('forma_farmaceutica', 'Comprimido').strip(),
                unidad_medida=request.POST.get('unidad_medida', 'comp'),
                categoria=cat,
                stock_minimo=int(request.POST.get('stock_minimo', 50)),
                stock_maximo=int(request.POST.get('stock_maximo', 1000)),
                es_controlado=es_ctrl,
            )
            registrar_auditoria(
                request.user,
                'Registro de Medicamento / Insumo en Arsenal (RF-03)',
                f'{med.codigo} - {med.nombre_generico}',
                valores_nuevos={'codigo': med.codigo, 'nombre': med.nombre_generico, 'controlado': med.es_controlado}
            )
            messages.success(request, f'Medicamento {med.nombre_generico} ({med.codigo}) registrado en el arsenal.')
            return redirect('farmacia:medicamento_list')
        except Exception as e:
            messages.error(request, f'Error al registrar medicamento: {e}')

    query = request.GET.get('q', '')
    categoria_id = request.GET.get('categoria', '')
    solo_quiebre = request.GET.get('quiebre', '')

    medicamentos = Medicamento.objects.filter(activo=True).select_related('categoria')

    if query:
        medicamentos = medicamentos.filter(
            Q(codigo__icontains=query) |
            Q(nombre_generico__icontains=query) |
            Q(nombre_comercial__icontains=query)
        )
    if categoria_id:
        medicamentos = medicamentos.filter(categoria_id=categoria_id)

    # Filtrar por quiebre de stock (se hace en Python por ser propiedad calculada)
    medicamentos_list = list(medicamentos)
    if solo_quiebre:
        medicamentos_list = [m for m in medicamentos_list if m.en_quiebre]

    categorias = CategoriaMedicamento.objects.all()

    return render(request, 'farmacia/medicamento_list.html', {
        'medicamentos': medicamentos_list,
        'categorias': categorias,
        'query': query,
        'categoria_id': categoria_id,
        'solo_quiebre': solo_quiebre,
    })


@login_required
@transaction.atomic
def medicamento_detalle(request, pk):
    """Detalle de medicamento con lotes ordenados FEFO y edición de parámetros / ajuste de lotes."""
    medicamento = get_object_or_404(Medicamento, pk=pk)

    if request.method == 'POST' and request.user.rol in ('admin', 'quimico', 'tecnico'):
        accion = request.POST.get('accion')
        if accion == 'editar_medicamento':
            try:
                ant = {'nombre': medicamento.nombre_generico, 'stock_minimo': medicamento.stock_minimo}
                medicamento.nombre_generico = request.POST.get('nombre_generico', medicamento.nombre_generico).strip()
                medicamento.nombre_comercial = request.POST.get('nombre_comercial', medicamento.nombre_comercial).strip()
                medicamento.concentracion = request.POST.get('concentracion', medicamento.concentracion).strip()
                medicamento.forma_farmaceutica = request.POST.get('forma_farmaceutica', medicamento.forma_farmaceutica).strip()
                medicamento.stock_minimo = int(request.POST.get('stock_minimo', medicamento.stock_minimo))
                medicamento.stock_maximo = int(request.POST.get('stock_maximo', medicamento.stock_maximo))
                if request.POST.get('categoria'):
                    medicamento.categoria_id = int(request.POST.get('categoria'))
                medicamento.es_controlado = request.POST.get('es_controlado') == 'on'
                medicamento.save()
                registrar_auditoria(
                    request.user,
                    'Edición de Ficha de Medicamento',
                    f'{medicamento.codigo} - {medicamento.nombre_generico}',
                    valores_anteriores=ant,
                    valores_nuevos={'nombre': medicamento.nombre_generico, 'stock_minimo': medicamento.stock_minimo}
                )
                messages.success(request, 'Parámetros del medicamento actualizados correctamente.')
            except Exception as e:
                messages.error(request, f'Error al editar medicamento: {e}')
            return redirect('farmacia:medicamento_detalle', pk=medicamento.pk)

        elif accion == 'ajustar_lote':
            try:
                lote = get_object_or_404(Lote, pk=request.POST.get('lote_id'), medicamento=medicamento)
                nueva_cant = int(request.POST.get('cantidad_actual', lote.cantidad_actual))
                motivo = request.POST.get('motivo', 'Ajuste manual de inventario').strip()
                cant_ant = lote.cantidad_actual
                lote.cantidad_actual = max(0, nueva_cant)
                if request.POST.get('fecha_vencimiento'):
                    lote.fecha_vencimiento = request.POST.get('fecha_vencimiento')
                lote.save()

                MovimientoStock.objects.create(
                    lote=lote,
                    tipo=MovimientoStock.TipoMovimiento.AJUSTE,
                    cantidad=lote.cantidad_actual - cant_ant,
                    cantidad_anterior=cant_ant,
                    cantidad_posterior=lote.cantidad_actual,
                    motivo=motivo,
                    usuario=request.user,
                    ubicacion_origen=lote.ubicacion,
                )
                registrar_auditoria(
                    request.user,
                    'Ajuste Manual de Stock en Lote',
                    f'Lote {lote.numero_lote} ({medicamento.nombre_generico})',
                    valores_anteriores={'cantidad': cant_ant},
                    valores_nuevos={'cantidad': lote.cantidad_actual, 'motivo': motivo}
                )
                messages.success(request, f'Lote {lote.numero_lote} ajustado a {lote.cantidad_actual} unidades.')
            except Exception as e:
                messages.error(request, f'Error al ajustar lote: {e}')
            return redirect('farmacia:medicamento_detalle', pk=medicamento.pk)

    lotes_fefo = medicamento.lotes_fefo()
    lotes_todos = medicamento.lotes.all().order_by('fecha_vencimiento')
    movimientos = MovimientoStock.objects.filter(
        lote__medicamento=medicamento
    ).order_by('-fecha')[:30]
    categorias = CategoriaMedicamento.objects.all()

    return render(request, 'farmacia/medicamento_detalle.html', {
        'medicamento': medicamento,
        'lotes_fefo': lotes_fefo,
        'lotes_todos': lotes_todos,
        'movimientos': movimientos,
        'categorias': categorias,
    })


@login_required
def lote_list(request):
    """Lista de lotes con filtros y ordenamiento FEFO."""
    query = request.GET.get('q', '')
    ubicacion_id = request.GET.get('ubicacion', '')
    alerta = request.GET.get('alerta', '')

    lotes = Lote.objects.filter(activo=True).select_related(
        'medicamento', 'ubicacion'
    ).order_by('fecha_vencimiento')

    if query:
        lotes = lotes.filter(
            Q(numero_lote__icontains=query) |
            Q(medicamento__nombre_generico__icontains=query)
        )
    if ubicacion_id:
        lotes = lotes.filter(ubicacion_id=ubicacion_id)
    if alerta:
        hoy = date.today()
        if alerta == 'vencido':
            lotes = lotes.filter(fecha_vencimiento__lte=hoy)
        elif alerta == '30':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hoy + timedelta(days=30))
        elif alerta == '60':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy + timedelta(days=30), fecha_vencimiento__lte=hoy + timedelta(days=60))
        elif alerta == '90':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy + timedelta(days=60), fecha_vencimiento__lte=hoy + timedelta(days=90))

    ubicaciones = Ubicacion.objects.filter(activa=True)

    return render(request, 'farmacia/lote_list.html', {
        'lotes': lotes,
        'ubicaciones': ubicaciones,
        'query': query,
        'ubicacion_id': ubicacion_id,
        'alerta': alerta,
    })


@login_required
def lote_crear(request):
    """Crear un nuevo lote de medicamento."""
    if request.method == 'POST':
        try:
            medicamento = Medicamento.objects.get(pk=request.POST.get('medicamento'))
            ubicacion = Ubicacion.objects.get(pk=request.POST.get('ubicacion'))
            cantidad = int(request.POST.get('cantidad_inicial', 0))

            lote = Lote.objects.create(
                medicamento=medicamento,
                numero_lote=request.POST.get('numero_lote'),
                fecha_fabricacion=request.POST.get('fecha_fabricacion'),
                fecha_vencimiento=request.POST.get('fecha_vencimiento'),
                cantidad_inicial=cantidad,
                cantidad_actual=cantidad,
                ubicacion=ubicacion,
                proveedor=request.POST.get('proveedor', ''),
            )

            # Registrar movimiento de ingreso
            MovimientoStock.objects.create(
                lote=lote,
                tipo=MovimientoStock.TipoMovimiento.INGRESO,
                cantidad=cantidad,
                cantidad_anterior=0,
                cantidad_posterior=cantidad,
                motivo=f'Ingreso inicial de lote {lote.numero_lote}',
                usuario=request.user,
                ubicacion_destino=ubicacion,
            )

            registrar_auditoria(
                request.user, 'Ingreso de lote', f'Lote {lote.numero_lote}',
                valores_nuevos={'medicamento': str(medicamento), 'cantidad': cantidad}
            )

            messages.success(request, f'Lote {lote.numero_lote} creado exitosamente.')
            return redirect('farmacia:lote_list')
        except Exception as e:
            messages.error(request, f'Error al crear lote: {e}')

    medicamentos = Medicamento.objects.filter(activo=True)
    ubicaciones = Ubicacion.objects.filter(activa=True)
    return render(request, 'farmacia/lote_form.html', {
        'medicamentos': medicamentos,
        'ubicaciones': ubicaciones,
    })


@login_required
def movimiento_list(request):
    """Historial de movimientos de stock."""
    movimientos = MovimientoStock.objects.all().select_related(
        'lote', 'lote__medicamento', 'usuario', 'ubicacion_origen', 'ubicacion_destino'
    )[:100]
    return render(request, 'farmacia/movimiento_list.html', {
        'movimientos': movimientos,
    })


@login_required
def traspaso(request):
    """Traspaso de stock entre bodega y vitrina (FEFO)."""
    if request.method == 'POST':
        try:
            lote = Lote.objects.get(pk=request.POST.get('lote'))
            cantidad = int(request.POST.get('cantidad', 0))
            destino = Ubicacion.objects.get(pk=request.POST.get('destino'))

            if cantidad > lote.cantidad_actual:
                messages.error(request, 'La cantidad a traspasar excede el stock disponible.')
                return redirect('farmacia:traspaso')

            if lote.esta_vencido:
                messages.error(request, 'No se puede traspasar un lote vencido.')
                return redirect('farmacia:traspaso')

            origen = lote.ubicacion
            cantidad_anterior = lote.cantidad_actual

            # Descontar del lote origen
            lote.cantidad_actual -= cantidad
            lote.save()

            # Crear o actualizar lote en destino
            lote_destino, created = Lote.objects.get_or_create(
                medicamento=lote.medicamento,
                numero_lote=lote.numero_lote,
                ubicacion=destino,
                defaults={
                    'fecha_fabricacion': lote.fecha_fabricacion,
                    'fecha_vencimiento': lote.fecha_vencimiento,
                    'cantidad_inicial': cantidad,
                    'cantidad_actual': cantidad,
                    'proveedor': lote.proveedor,
                }
            )
            if not created:
                lote_destino.cantidad_actual += cantidad
                lote_destino.save()

            tipo_mov = MovimientoStock.TipoMovimiento.TRASPASO_BODEGA_VITRINA
            if destino.tipo == Ubicacion.TipoUbicacion.BODEGA:
                tipo_mov = MovimientoStock.TipoMovimiento.TRASPASO_VITRINA_BODEGA

            MovimientoStock.objects.create(
                lote=lote,
                tipo=tipo_mov,
                cantidad=cantidad,
                cantidad_anterior=cantidad_anterior,
                cantidad_posterior=lote.cantidad_actual,
                motivo=f'Traspaso a {destino.nombre}',
                usuario=request.user,
                ubicacion_origen=origen,
                ubicacion_destino=destino,
            )

            registrar_auditoria(
                request.user, 'Traspaso de stock', f'Lote {lote.numero_lote}',
                valores_anteriores={'ubicacion': str(origen), 'cantidad': cantidad_anterior},
                valores_nuevos={'ubicacion': str(destino), 'cantidad_traspasada': cantidad}
            )

            messages.success(request, f'Se traspasaron {cantidad} unidades del lote {lote.numero_lote} a {destino.nombre}.')
            return redirect('farmacia:movimiento_list')
        except Exception as e:
            messages.error(request, f'Error en el traspaso: {e}')

    lotes = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')
    ubicaciones = Ubicacion.objects.filter(activa=True)

    return render(request, 'farmacia/traspaso.html', {
        'lotes': lotes,
        'ubicaciones': ubicaciones,
    })


@login_required
def alertas_vencimiento(request):
    """Alertas de vencimiento próximo (30/60/90 días) y quiebre de stock."""
    hoy = date.today()

    alertas_30 = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hoy + timedelta(days=30)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    alertas_60 = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy + timedelta(days=30), fecha_vencimiento__lte=hoy + timedelta(days=60)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    alertas_90 = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy + timedelta(days=60), fecha_vencimiento__lte=hoy + timedelta(days=90)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    vencidos = Lote.objects.filter(
        activo=True, cantidad_actual__gt=0, fecha_vencimiento__lte=hoy
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    # Medicamentos en quiebre de stock
    medicamentos_quiebre = [
        m for m in Medicamento.objects.filter(activo=True).select_related('categoria')
        if m.en_quiebre
    ]

    # Guardar alertas en MongoDB
    try:
        from core.mongo_client import get_mongo_db
        from datetime import datetime, timezone as tz
        db = get_mongo_db()
        if db is not None:
            for lote in alertas_30:
                db.alertas_sistema.insert_one({
                    'timestamp': datetime.now(tz.utc).isoformat(),
                    'tipo': 'vencimiento_30',
                    'medicamento': lote.medicamento.nombre_generico,
                    'lote': lote.numero_lote,
                    'fecha_vencimiento': lote.fecha_vencimiento.isoformat(),
                    'dias_restantes': lote.dias_para_vencer,
                    'leido': False,
                })
    except Exception:
        pass

    return render(request, 'farmacia/alertas_vencimiento.html', {
        'vencidos': vencidos,
        'alertas_30': alertas_30,
        'alertas_60': alertas_60,
        'alertas_90': alertas_90,
        'medicamentos_quiebre': medicamentos_quiebre,
    })


@login_required
@transaction.atomic
def orden_list(request):
    """
    Módulo de Abastecimiento y Pedidos a CENABAST (RF-04, RF-06).
    Permite listar órdenes, crear pedidos manuales multi-ítem (con medicamentos existentes
    o incorporando nuevos medicamentos que aún no están en el catálogo) o disparar pedidos automáticos.
    """
    if request.method == 'POST':
        try:
            tipo = request.POST.get('tipo', 'cenabast')
            obs = request.POST.get('observaciones', '').strip()
            proveedor = request.POST.get('proveedor', 'CENABAST - Central de Abastecimiento del S.N.S.S.').strip()

            correlativo = OrdenAbastecimiento.objects.count() + 1
            while OrdenAbastecimiento.objects.filter(numero_orden=f'OC-CENABAST-2026-{correlativo:04d}').exists():
                correlativo += 1
            num_orden = f'OC-CENABAST-2026-{correlativo:04d}'

            orden = OrdenAbastecimiento.objects.create(
                numero_orden=num_orden,
                tipo=tipo,
                estado=OrdenAbastecimiento.EstadoOrden.PENDIENTE,
                proveedor=proveedor,
                solicitante=request.user,
                generada_automaticamente=False,
                observaciones=obs or 'Orden de abastecimiento manual confeccionada por Farmacia CESFAM.',
            )

            items_agregados = []

            # 1) Procesar medicamentos existentes seleccionados en las filas dinámicas
            med_ids = request.POST.getlist('medicamento_id')
            cantidades = request.POST.getlist('cantidad_solicitada')
            for i in range(len(med_ids)):
                if med_ids[i]:
                    med_obj = Medicamento.objects.get(pk=int(med_ids[i]))
                    cant_val = int(cantidades[i]) if i < len(cantidades) and cantidades[i] else 100
                    if cant_val > 0:
                        DetalleOrdenAbastecimiento.objects.create(
                            orden=orden,
                            medicamento=med_obj,
                            stock_al_solicitar=med_obj.stock_total,
                            cantidad_solicitada=cant_val,
                        )
                        items_agregados.append(f'{med_obj.nombre_generico} x{cant_val}')

            # 2) Procesar si el usuario incorporó un NUEVO medicamento que no estaba en el catálogo
            incluir_nuevo = request.POST.get('incluir_nuevo_med') == 'on'
            nuevo_nombre = request.POST.get('nuevo_nombre_generico', '').strip()
            if incluir_nuevo and nuevo_nombre:
                nuevo_codigo = request.POST.get('nuevo_codigo', '').strip().upper()
                if not nuevo_codigo:
                    nuevo_codigo = f'MED-NEW-{Medicamento.objects.count() + 1:03d}'
                cat_id = request.POST.get('nuevo_categoria')
                cat_obj = CategoriaMedicamento.objects.get(pk=cat_id) if cat_id else CategoriaMedicamento.objects.first()
                es_ctrl = request.POST.get('nuevo_es_controlado') == 'on' or (cat_obj and cat_obj.es_controlado)

                nuevo_med, _ = Medicamento.objects.get_or_create(
                    codigo=nuevo_codigo,
                    defaults={
                        'nombre_generico': nuevo_nombre,
                        'nombre_comercial': request.POST.get('nuevo_nombre_comercial', '').strip(),
                        'concentracion': request.POST.get('nuevo_concentracion', 'S/C').strip(),
                        'forma_farmaceutica': request.POST.get('nuevo_forma_farmaceutica', 'Comprimido').strip(),
                        'unidad_medida': request.POST.get('nuevo_unidad_medida', 'comp'),
                        'categoria': cat_obj,
                        'stock_minimo': int(request.POST.get('nuevo_stock_minimo', 50) or 50),
                        'stock_maximo': int(request.POST.get('nuevo_stock_maximo', 1000) or 1000),
                        'es_controlado': es_ctrl,
                    }
                )
                cant_nuevo = int(request.POST.get('nuevo_cantidad_solicitada', 200) or 200)
                DetalleOrdenAbastecimiento.objects.create(
                    orden=orden,
                    medicamento=nuevo_med,
                    stock_al_solicitar=nuevo_med.stock_total,
                    cantidad_solicitada=cant_nuevo,
                )
                items_agregados.append(f'[NUEVO EN CATÁLOGO] {nuevo_med.nombre_generico} ({nuevo_med.codigo}) x{cant_nuevo}')

            if not items_agregados:
                # Si no seleccionó ninguno, redirigir igual al editor de la orden para que agregue ítems
                messages.warning(request, f'Orden {orden.numero_orden} creada en borrador. Agregue los medicamentos requeridos a continuación.')
            else:
                registrar_auditoria(
                    request.user,
                    'Emisión Manual de Orden de Abastecimiento CENABAST',
                    f'Orden {orden.numero_orden}',
                    valores_nuevos={'items': items_agregados, 'proveedor': proveedor}
                )
                messages.success(request, f'Orden {orden.numero_orden} creada con {len(items_agregados)} ítem(s). Puede revisarla o editarla antes de visar.')

            return redirect('farmacia:orden_detalle', pk=orden.pk)
        except Exception as e:
            messages.error(request, f'Error al generar orden: {e}')

    ordenes = OrdenAbastecimiento.objects.all().prefetch_related('detalles', 'detalles__medicamento')
    todos_meds = list(Medicamento.objects.filter(activo=True).select_related('categoria'))
    medicamentos_quiebre = [m for m in todos_meds if m.en_quiebre]
    categorias = CategoriaMedicamento.objects.all()

    return render(request, 'farmacia/orden_list.html', {
        'ordenes': ordenes,
        'medicamentos': todos_meds,
        'medicamentos_quiebre': medicamentos_quiebre,
        'categorias': categorias,
    })


@login_required
@transaction.atomic
def generar_orden_automatica(request):
    """
    Detecta todos los fármacos en quiebre de stock (bajo stock_minimo) o con stock crítico
    y genera una Orden de Pedido en estado PENDIENTE (Borrador Editable) para que el usuario
    pueda revisarla, modificar cantidades, quitar o agregar medicamentos antes de enviarla.
    """
    todos_meds = list(Medicamento.objects.filter(activo=True))
    meds_criticos = [m for m in todos_meds if m.en_quiebre]

    if not meds_criticos:
        meds_criticos = sorted(todos_meds, key=lambda m: m.stock_total)[:2]

    correlativo = OrdenAbastecimiento.objects.count() + 1
    while OrdenAbastecimiento.objects.filter(numero_orden=f'OC-CENABAST-2026-{correlativo:04d}').exists():
        correlativo += 1
    num_orden = f'OC-CENABAST-2026-{correlativo:04d}'

    orden = OrdenAbastecimiento.objects.create(
        numero_orden=num_orden,
        tipo=OrdenAbastecimiento.TipoOrden.URGENCIA_QUIEBRE,
        estado=OrdenAbastecimiento.EstadoOrden.PENDIENTE,
        proveedor='CENABAST - Central de Abastecimiento del S.N.S.S.',
        solicitante=request.user,
        generada_automaticamente=True,
        observaciones='Propuesta automática generada por detección de stock bajo el umbral mínimo ministerial (RF-06). Sujeta a revisión y edición por Farmacia.',
    )

    items_creados = []
    for med in meds_criticos:
        deficit = max(med.stock_maximo - med.stock_total, med.stock_minimo * 3)
        DetalleOrdenAbastecimiento.objects.create(
            orden=orden,
            medicamento=med,
            stock_al_solicitar=med.stock_total,
            cantidad_solicitada=deficit,
        )
        items_creados.append(f'{med.nombre_generico} (+{deficit})')

    registrar_auditoria(
        request.user,
        'Generación de Propuesta de Orden CENABAST por Quiebre de Stock (RF-06)',
        f'Orden {orden.numero_orden}',
        valores_nuevos={'items_sugeridos': items_creados}
    )

    messages.info(
        request,
        f'Propuesta {orden.numero_orden} generada en estado PENDIENTE (Editable). Puedes revisar, cambiar cantidades, eliminar ítems o agregar nuevos medicamentos antes de visarla.'
    )
    return redirect('farmacia:orden_detalle', pk=orden.pk)


@login_required
@transaction.atomic
def orden_detalle(request, pk):
    """
    Editor Completo, Visación e Impresión de Orden de Abastecimiento CENABAST.
    Permite:
      - Editar cabecera (tipo, proveedor, observaciones)
      - Modificar la cantidad solicitada de cualquier ítem
      - Eliminar cualquier ítem de la orden
      - Agregar un medicamento ya existente en el catálogo
      - Crear un NUEVO medicamento que no existe en el catálogo e incluirlo en la orden
      - Reabrir una orden enviada para seguir editándola
      - Anular o eliminar la orden
      - Visar como Q.F. y Enviar a CENABAST
      - Recepcionar la remesa en Bodega Central creando automáticamente los Lotes FEFO.
    """
    orden = get_object_or_404(OrdenAbastecimiento, pk=pk)
    detalles = orden.detalles.all().select_related('medicamento', 'lote_recibido')

    if request.method == 'POST':
        accion = request.POST.get('accion')

        # 1. Editar datos generales de la cabecera
        if accion == 'editar_cabecera' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            ant = {'tipo': orden.tipo, 'proveedor': orden.proveedor, 'observaciones': orden.observaciones}
            orden.tipo = request.POST.get('tipo', orden.tipo)
            orden.proveedor = request.POST.get('proveedor', orden.proveedor).strip()
            orden.observaciones = request.POST.get('observaciones', orden.observaciones).strip()
            orden.save()
            registrar_auditoria(
                request.user,
                'Edición de Cabecera de Orden CENABAST',
                f'Orden {orden.numero_orden}',
                valores_anteriores=ant,
                valores_nuevos={'tipo': orden.tipo, 'proveedor': orden.proveedor, 'observaciones': orden.observaciones}
            )
            messages.success(request, 'Datos generales de la orden actualizados.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 2. Actualizar la cantidad solicitada de un ítem específico
        elif accion == 'actualizar_item' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            det = get_object_or_404(DetalleOrdenAbastecimiento, pk=request.POST.get('detalle_id'), orden=orden)
            cant_ant = det.cantidad_solicitada
            nueva_cant = int(request.POST.get('cantidad_solicitada', cant_ant))
            if nueva_cant <= 0:
                nombre_med = det.medicamento.nombre_generico
                det.delete()
                messages.warning(request, f'Ítem {nombre_med} eliminado de la orden.')
            else:
                det.cantidad_solicitada = nueva_cant
                det.save()
                registrar_auditoria(
                    request.user,
                    'Modificación de Cantidad en Orden CENABAST',
                    f'Orden {orden.numero_orden} - {det.medicamento.nombre_generico}',
                    valores_anteriores={'cantidad_solicitada': cant_ant},
                    valores_nuevos={'cantidad_solicitada': nueva_cant}
                )
                messages.success(request, f'Cantidad de {det.medicamento.nombre_generico} actualizada a {nueva_cant} unidades.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 3. Eliminar un ítem de la orden
        elif accion == 'eliminar_item' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            det = get_object_or_404(DetalleOrdenAbastecimiento, pk=request.POST.get('detalle_id'), orden=orden)
            nombre_med = det.medicamento.nombre_generico
            cant_ant = det.cantidad_solicitada
            det.delete()
            registrar_auditoria(
                request.user,
                'Eliminación de Ítem en Orden CENABAST',
                f'Orden {orden.numero_orden}',
                valores_anteriores={'medicamento_eliminado': nombre_med, 'cantidad': cant_ant},
                valores_nuevos={}
            )
            messages.warning(request, f'Se quitó "{nombre_med}" de la orden {orden.numero_orden}.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 4. Agregar un medicamento existente del catálogo a la orden
        elif accion == 'agregar_item_existente' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            med = get_object_or_404(Medicamento, pk=request.POST.get('medicamento_id'))
            cant = int(request.POST.get('cantidad_solicitada', 100) or 100)
            det_existente = DetalleOrdenAbastecimiento.objects.filter(orden=orden, medicamento=med).first()
            if det_existente:
                cant_ant = det_existente.cantidad_solicitada
                det_existente.cantidad_solicitada += cant
                det_existente.save()
                messages.success(request, f'Se sumaron {cant} unidades a {med.nombre_generico} (Total: {det_existente.cantidad_solicitada}).')
            else:
                DetalleOrdenAbastecimiento.objects.create(
                    orden=orden,
                    medicamento=med,
                    stock_al_solicitar=med.stock_total,
                    cantidad_solicitada=cant,
                )
                messages.success(request, f'Se agregó "{med.nombre_generico}" ({cant} unidades) a la orden.')
            registrar_auditoria(
                request.user,
                'Adición de Medicamento a Orden CENABAST',
                f'Orden {orden.numero_orden}',
                valores_nuevos={'medicamento': med.nombre_generico, 'cantidad': cant}
            )
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 5. Crear un NUEVO medicamento que no existe en el catálogo y agregarlo a la orden
        elif accion == 'agregar_item_nuevo' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            try:
                codigo = request.POST.get('codigo', '').strip().upper()
                if not codigo:
                    codigo = f'MED-NEW-{Medicamento.objects.count() + 1:03d}'
                nombre_gen = request.POST.get('nombre_generico', '').strip()
                cat_obj = CategoriaMedicamento.objects.get(pk=request.POST.get('categoria'))
                es_ctrl = request.POST.get('es_controlado') == 'on' or cat_obj.es_controlado

                nuevo_med, created = Medicamento.objects.get_or_create(
                    codigo=codigo,
                    defaults={
                        'nombre_generico': nombre_gen,
                        'nombre_comercial': request.POST.get('nombre_comercial', '').strip(),
                        'concentracion': request.POST.get('concentracion', '').strip(),
                        'forma_farmaceutica': request.POST.get('forma_farmaceutica', 'Comprimido').strip(),
                        'unidad_medida': request.POST.get('unidad_medida', 'comp'),
                        'categoria': cat_obj,
                        'stock_minimo': int(request.POST.get('stock_minimo', 50) or 50),
                        'stock_maximo': int(request.POST.get('stock_maximo', 1000) or 1000),
                        'es_controlado': es_ctrl,
                    }
                )
                cant_sol = int(request.POST.get('cantidad_solicitada', 200) or 200)
                DetalleOrdenAbastecimiento.objects.create(
                    orden=orden,
                    medicamento=nuevo_med,
                    stock_al_solicitar=nuevo_med.stock_total,
                    cantidad_solicitada=cant_sol,
                )
                registrar_auditoria(
                    request.user,
                    'Creación de Nuevo Medicamento en Catálogo e Inclusión en Orden CENABAST',
                    f'Orden {orden.numero_orden} - {nuevo_med.codigo}',
                    valores_nuevos={'codigo': nuevo_med.codigo, 'nombre': nuevo_med.nombre_generico, 'cantidad_solicitada': cant_sol}
                )
                messages.success(
                    request,
                    f'Nuevo medicamento "{nuevo_med.nombre_generico} ({nuevo_med.codigo})" registrado en el catálogo del CESFAM y agregado a la orden ({cant_sol} unid.).'
                )
            except Exception as e:
                messages.error(request, f'Error al registrar nuevo medicamento en la orden: {e}')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 6. Reabrir orden a estado Pendiente (Edición)
        elif accion == 'reabrir_edicion' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            est_ant = orden.estado
            orden.estado = OrdenAbastecimiento.EstadoOrden.PENDIENTE
            orden.save()
            registrar_auditoria(
                request.user,
                'Reapertura de Orden CENABAST para Edición',
                f'Orden {orden.numero_orden}',
                valores_anteriores={'estado': est_ant},
                valores_nuevos={'estado': 'pendiente'}
            )
            messages.info(request, f'Orden {orden.numero_orden} reabierta en modo Edición.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 7. Anular orden
        elif accion == 'anular_orden' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            est_ant = orden.estado
            orden.estado = OrdenAbastecimiento.EstadoOrden.ANULADA
            orden.save()
            registrar_auditoria(
                request.user,
                'Anulación de Orden CENABAST',
                f'Orden {orden.numero_orden}',
                valores_anteriores={'estado': est_ant},
                valores_nuevos={'estado': 'anulada'}
            )
            messages.warning(request, f'Orden {orden.numero_orden} fue ANULADA.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 8. Eliminar orden en borrador/anulada
        elif accion == 'eliminar_orden' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            num = orden.numero_orden
            orden.delete()
            registrar_auditoria(
                request.user,
                'Eliminación de Orden CENABAST en Borrador',
                f'Orden {num}',
                valores_anteriores={'numero_orden': num},
                valores_nuevos={}
            )
            messages.warning(request, f'Orden {num} eliminada permanentemente.')
            return redirect('farmacia:orden_list')

        # 9. Visar / Aprobar como Q.F.
        elif accion == 'aprobar' and request.user.rol in ('admin', 'quimico'):
            if not detalles.exists():
                messages.error(request, 'No se puede visar una orden vacía sin medicamentos.')
                return redirect('farmacia:orden_detalle', pk=orden.pk)
            orden.estado = OrdenAbastecimiento.EstadoOrden.ENVIADA
            orden.aprobador_qf = request.user
            orden.save()
            registrar_auditoria(
                request.user,
                'Visación Técnica Q.F. y Envío de Orden a CENABAST',
                f'Orden {orden.numero_orden}',
                valores_anteriores={'estado': 'pendiente'},
                valores_nuevos={'estado': 'enviada', 'aprobador_qf': request.user.get_full_name()}
            )
            messages.success(request, f'Orden {orden.numero_orden} visada por Q.F. y enviada a CENABAST.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 10. Recepcionar remesa en Bodega Central
        elif accion == 'recepcionar':
            if not detalles.exists():
                messages.error(request, 'La orden no tiene ítems para recepcionar.')
                return redirect('farmacia:orden_detalle', pk=orden.pk)
            guia = request.POST.get('guia_despacho', f'GD-CEN-{orden.id:04d}').strip()
            bodega = Ubicacion.objects.filter(tipo=Ubicacion.TipoUbicacion.BODEGA).first()
            if not bodega:
                bodega = Ubicacion.objects.first()

            hoy = date.today()
            lotes_creados = []

            for det in detalles:
                num_lote = request.POST.get(f'lote_{det.id}', f'CEN-2026-{orden.id:02d}{det.id:02d}').strip()
                f_venc = request.POST.get(f'vencimiento_{det.id}') or (hoy + timedelta(days=365)).isoformat()
                cant_rec = int(request.POST.get(f'cantidad_{det.id}', det.cantidad_solicitada))

                nuevo_lote, created = Lote.objects.get_or_create(
                    medicamento=det.medicamento,
                    numero_lote=num_lote,
                    ubicacion=bodega,
                    defaults={
                        'fecha_fabricacion': hoy - timedelta(days=30),
                        'fecha_vencimiento': f_venc,
                        'cantidad_inicial': cant_rec,
                        'cantidad_actual': cant_rec,
                        'proveedor': orden.proveedor,
                    }
                )
                stock_ant = 0 if created else nuevo_lote.cantidad_actual
                if not created:
                    nuevo_lote.cantidad_actual += cant_rec
                    nuevo_lote.save()

                det.cantidad_recibida = cant_rec
                det.lote_recibido = nuevo_lote
                det.save()

                MovimientoStock.objects.create(
                    lote=nuevo_lote,
                    tipo=MovimientoStock.TipoMovimiento.INGRESO,
                    cantidad=cant_rec,
                    cantidad_anterior=stock_ant,
                    cantidad_posterior=nuevo_lote.cantidad_actual,
                    motivo=f'Recepción Remesa CENABAST Orden {orden.numero_orden} (Guía {guia})',
                    usuario=request.user,
                    ubicacion_destino=bodega,
                )
                lotes_creados.append(f'{num_lote} (+{cant_rec})')

            orden.estado = OrdenAbastecimiento.EstadoOrden.RECEPCIONADA
            orden.guia_despacho = guia
            orden.fecha_recepcion = timezone.now()
            if not orden.aprobador_qf:
                orden.aprobador_qf = request.user
            orden.save()

            registrar_auditoria(
                request.user,
                'Recepción Conforme de Remesa CENABAST e Ingreso a Bodega Central',
                f'Orden {orden.numero_orden} (Guía {guia})',
                valores_anteriores={'estado': 'enviada'},
                valores_nuevos={'estado': 'recepcionada', 'guia_despacho': guia, 'lotes_ingresados': lotes_creados}
            )
            messages.success(
                request,
                f'✅ Remesa de la Orden {orden.numero_orden} recepcionada en {bodega.nombre}. El stock se incrementó automáticamente.'
            )
            return redirect('farmacia:orden_detalle', pk=orden.pk)

    sugerencia_vencimiento = (date.today() + timedelta(days=365)).isoformat()
    todos_medicamentos = Medicamento.objects.filter(activo=True).order_by('nombre_generico')
    categorias = CategoriaMedicamento.objects.all()

    return render(request, 'farmacia/orden_detalle.html', {
        'orden': orden,
        'detalles': detalles,
        'sugerencia_vencimiento': sugerencia_vencimiento,
        'todos_medicamentos': todos_medicamentos,
        'categorias': categorias,
        'tipos_orden': OrdenAbastecimiento.TipoOrden.choices,
    })
