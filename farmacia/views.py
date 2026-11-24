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
from core.decorators import rol_requerido, denegar_acceso


@rol_requerido('admin', 'quimico', 'tecnico', 'clinico')
def medicamento_list(request):
    """Lista de medicamentos con búsqueda, filtros, edición y alta ágil con lote inicial en 1 paso (RF-03)."""
    if request.method == 'POST':
        if request.user.rol not in ('admin', 'quimico'):
            return denegar_acceso(
                request,
                motivo='Solo el Administrador y el Químico Farmacéutico pueden incorporar nuevos medicamentos o modificar el catálogo base.',
                roles_autorizados=('admin', 'quimico')
            )

        accion = request.POST.get('accion', 'crear').strip()

        if accion == 'editar_medicamento':
            try:
                med = get_object_or_404(Medicamento, pk=request.POST.get('medicamento_id'))
                codigo = request.POST.get('codigo', '').strip().upper()
                nombre_generico = request.POST.get('nombre_generico', '').strip()
                nombre_comercial = request.POST.get('nombre_comercial', '').strip()
                concentracion = request.POST.get('concentracion', '').strip()
                forma_farmaceutica = request.POST.get('forma_farmaceutica', '').strip()
                unidad_medida = request.POST.get('unidad_medida', med.unidad_medida).strip()
                stock_minimo = int(request.POST.get('stock_minimo', 0) or 0)
                stock_maximo = int(request.POST.get('stock_maximo', 0) or 0)
                cat = get_object_or_404(CategoriaMedicamento, pk=request.POST.get('categoria'))

                if not codigo or not nombre_generico or not concentracion or not forma_farmaceutica:
                    raise ValueError('Complete los campos obligatorios: Código, Nombre Genérico, Concentración y Forma Farmacéutica.')
                if Medicamento.objects.exclude(pk=med.pk).filter(codigo__iexact=codigo).exists():
                    raise ValueError(f'Ya existe otro medicamento o insumo con el código interno "{codigo}".')
                if stock_minimo <= 0 or stock_maximo < stock_minimo:
                    raise ValueError('El stock mínimo debe ser mayor a 0 y la capacidad máxima debe ser mayor o igual al stock mínimo.')
                if unidad_medida not in dict(Medicamento.UnidadMedida.choices):
                    unidad_medida = med.unidad_medida

                es_ctrl = request.POST.get('es_controlado') == 'on'
                ant = {
                    'codigo': med.codigo,
                    'nombre': med.nombre_generico,
                    'concentracion': med.concentracion,
                    'categoria': med.categoria.nombre,
                    'stock_minimo': med.stock_minimo,
                    'stock_maximo': med.stock_maximo,
                    'controlado': med.es_controlado,
                }
                med.codigo = codigo
                med.nombre_generico = nombre_generico
                med.nombre_comercial = nombre_comercial
                med.concentracion = concentracion
                med.forma_farmaceutica = forma_farmaceutica
                med.unidad_medida = unidad_medida
                med.categoria = cat
                med.stock_minimo = stock_minimo
                med.stock_maximo = stock_maximo
                med.es_controlado = es_ctrl
                med.save()

                registrar_auditoria(
                    request.user,
                    'Edición de Medicamento / Insumo en Arsenal (RF-03)',
                    f'{med.codigo} - {med.nombre_generico}',
                    valores_anteriores=ant,
                    valores_nuevos={
                        'codigo': med.codigo,
                        'nombre': med.nombre_generico,
                        'concentracion': med.concentracion,
                        'categoria': med.categoria.nombre,
                        'stock_minimo': med.stock_minimo,
                        'stock_maximo': med.stock_maximo,
                        'controlado': med.es_controlado,
                    }
                )
                messages.success(request, f'Ficha de {med.nombre_generico} ({med.codigo}) actualizada correctamente.')
                return redirect('farmacia:medicamento_list')
            except ValueError as ve:
                messages.error(request, str(ve))
            except Exception as e:
                messages.error(request, f'Error al editar medicamento: {e}')
            return redirect('farmacia:medicamento_list')

        # Alta de nuevo medicamento / insumo (con opción atómica de lote inicial en 1 paso)
        try:
            with transaction.atomic():
                codigo = request.POST.get('codigo', '').strip().upper()
                nombre_generico = request.POST.get('nombre_generico', '').strip()
                nombre_comercial = request.POST.get('nombre_comercial', '').strip()
                concentracion = request.POST.get('concentracion', '').strip()
                forma_farmaceutica = request.POST.get('forma_farmaceutica', 'Comprimido').strip()
                unidad_medida = request.POST.get('unidad_medida', 'comp').strip()
                stock_minimo = int(request.POST.get('stock_minimo', 0) or 0)
                stock_maximo = int(request.POST.get('stock_maximo', 0) or 0)
                cat = get_object_or_404(CategoriaMedicamento, pk=request.POST.get('categoria'))

                if not codigo or not nombre_generico or not concentracion or not forma_farmaceutica:
                    raise ValueError('Complete los campos obligatorios: Código Interno, Nombre Genérico (DCI), Concentración y Forma Farmacéutica.')
                if Medicamento.objects.filter(codigo__iexact=codigo).exists():
                    raise ValueError(f'El código interno "{codigo}" ya se encuentra registrado en el Arsenal.')
                if stock_minimo <= 0 or stock_maximo < stock_minimo:
                    raise ValueError('El stock mínimo debe ser mayor a 0 y la capacidad máxima debe ser mayor o igual al stock mínimo.')
                if unidad_medida not in dict(Medicamento.UnidadMedida.choices):
                    unidad_medida = Medicamento.UnidadMedida.COMPRIMIDO

                es_ctrl = request.POST.get('es_controlado') == 'on' or cat.es_controlado
                med = Medicamento.objects.create(
                    codigo=codigo,
                    nombre_generico=nombre_generico,
                    nombre_comercial=nombre_comercial,
                    concentracion=concentracion,
                    forma_farmaceutica=forma_farmaceutica,
                    unidad_medida=unidad_medida,
                    categoria=cat,
                    stock_minimo=stock_minimo,
                    stock_maximo=stock_maximo,
                    es_controlado=es_ctrl,
                )

                ingresar_lote = request.POST.get('ingresar_lote_inicial') == 'on'
                if ingresar_lote:
                    numero_lote = request.POST.get('numero_lote', '').strip()
                    fecha_fab_str = request.POST.get('fecha_fabricacion', '').strip()
                    fecha_venc_str = request.POST.get('fecha_vencimiento', '').strip()
                    cantidad_inicial = int(request.POST.get('cantidad_inicial', 0) or 0)
                    ubicacion_id_lote = request.POST.get('ubicacion_lote', '').strip()
                    motivo_lote = (
                        request.POST.get('motivo_lote', '').strip()
                        or 'Ingreso inicial al Arsenal / Remesa CENABAST'
                    )
                    proveedor_lote = request.POST.get('proveedor_lote', '').strip() or 'CENABAST'

                    if not numero_lote:
                        raise ValueError('Para ingresar stock inicial debe indicar el N° de Lote.')
                    if cantidad_inicial <= 0:
                        raise ValueError('La cantidad inicial del lote debe ser mayor a cero.')
                    if not fecha_fab_str or not fecha_venc_str:
                        raise ValueError('Debe indicar la Fecha de Fabricación y la Fecha de Vencimiento del lote inicial.')
                    if not ubicacion_id_lote:
                        raise ValueError('Debe seleccionar una Ubicación (Bodega o Vitrina) para el lote inicial.')

                    ubicacion = get_object_or_404(Ubicacion, pk=ubicacion_id_lote, activa=True)
                    fecha_fab = date.fromisoformat(fecha_fab_str)
                    fecha_venc = date.fromisoformat(fecha_venc_str)
                    hoy = date.today()

                    if fecha_venc <= fecha_fab:
                        raise ValueError('La fecha de vencimiento del lote inicial debe ser posterior a la fecha de fabricación.')
                    if fecha_venc < hoy and ubicacion.tipo == Ubicacion.TipoUbicacion.VITRINA:
                        raise ValueError(
                            f'No se puede ingresar un lote ya vencido ({fecha_venc.strftime("%d/%m/%Y")}) directamente en {ubicacion.nombre}.'
                        )

                    lote = Lote.objects.create(
                        medicamento=med,
                        numero_lote=numero_lote,
                        fecha_fabricacion=fecha_fab,
                        fecha_vencimiento=fecha_venc,
                        cantidad_inicial=cantidad_inicial,
                        cantidad_actual=cantidad_inicial,
                        ubicacion=ubicacion,
                        proveedor=proveedor_lote,
                    )

                    MovimientoStock.objects.create(
                        lote=lote,
                        tipo=MovimientoStock.TipoMovimiento.INGRESO,
                        cantidad=cantidad_inicial,
                        cantidad_anterior=0,
                        cantidad_posterior=cantidad_inicial,
                        motivo=f'Ingreso inicial al Arsenal — Lote {lote.numero_lote}: {motivo_lote}',
                        usuario=request.user,
                        ubicacion_destino=ubicacion,
                    )

                    if med.es_controlado:
                        from controlados.models import LibroControlados
                        LibroControlados.objects.create(
                            folio=LibroControlados.siguiente_folio(),
                            medicamento=med,
                            lote=lote,
                            tipo_movimiento=LibroControlados.TipoMovimiento.INGRESO,
                            cantidad=cantidad_inicial,
                            saldo_anterior=0,
                            saldo_posterior=cantidad_inicial,
                            quimico_responsable=request.user,
                            verificacion_2fa=True,
                            observaciones=f'Ingreso inicial desde Arsenal — Lote {lote.numero_lote}: {motivo_lote}',
                        )

                    registrar_auditoria(
                        request.user,
                        'Registro de Medicamento / Insumo en Arsenal con Lote Inicial (RF-03)',
                        f'{med.codigo} - {med.nombre_generico} (Lote {lote.numero_lote})',
                        valores_nuevos={
                            'codigo': med.codigo,
                            'nombre': med.nombre_generico,
                            'concentracion': med.concentracion,
                            'controlado': med.es_controlado,
                            'lote_inicial': lote.numero_lote,
                            'cantidad_inicial': cantidad_inicial,
                            'ubicacion': ubicacion.nombre,
                            'motivo': motivo_lote,
                        }
                    )
                    messages.success(
                        request,
                        f'{med.nombre_generico} ({med.codigo}) registrado en el Arsenal junto con el lote FEFO '
                        f'"{lote.numero_lote}" ({cantidad_inicial} unid. en {ubicacion.nombre}) y movimiento inicial en Kardex.'
                    )
                else:
                    registrar_auditoria(
                        request.user,
                        'Registro de Medicamento / Insumo en Arsenal (RF-03)',
                        f'{med.codigo} - {med.nombre_generico}',
                        valores_nuevos={
                            'codigo': med.codigo,
                            'nombre': med.nombre_generico,
                            'concentracion': med.concentracion,
                            'controlado': med.es_controlado,
                        }
                    )
                    messages.success(request, f'Medicamento {med.nombre_generico} ({med.codigo}) registrado en el arsenal.')
                return redirect('farmacia:medicamento_list')
        except ValueError as ve:
            messages.error(request, str(ve))
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
    ubicaciones = Ubicacion.objects.filter(activa=True).order_by('tipo', 'nombre')
    hoy = date.today()

    return render(request, 'farmacia/medicamento_list.html', {
        'medicamentos': medicamentos_list,
        'categorias': categorias,
        'ubicaciones': ubicaciones,
        'unidades_medida': Medicamento.UnidadMedida.choices,
        'hoy_iso': hoy.isoformat(),
        'venc_default_iso': (hoy + timedelta(days=365)).isoformat(),
        'query': query,
        'categoria_id': categoria_id,
        'solo_quiebre': solo_quiebre,
    })


@rol_requerido('admin', 'quimico', 'tecnico', 'clinico')
@transaction.atomic
def medicamento_detalle(request, pk):
    """Detalle de medicamento con lotes ordenados FEFO y edición de parámetros / ajuste de lotes."""
    medicamento = get_object_or_404(Medicamento, pk=pk)

    if request.method == 'POST':
        if request.user.rol not in ('admin', 'quimico'):
            return denegar_acceso(
                request,
                motivo='Solo el Administrador y el Químico Farmacéutico pueden editar parámetros técnicos o realizar ajustes de arqueo sobre lotes.',
                roles_autorizados=('admin', 'quimico')
            )
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
    lote_bodega_sugerido = lotes_fefo.filter(ubicacion__tipo=Ubicacion.TipoUbicacion.BODEGA).first()
    movimientos = MovimientoStock.objects.filter(
        lote__medicamento=medicamento
    ).order_by('-fecha')[:30]
    categorias = CategoriaMedicamento.objects.all()

    return render(request, 'farmacia/medicamento_detalle.html', {
        'medicamento': medicamento,
        'lotes_fefo': lotes_fefo,
        'lotes_todos': lotes_todos,
        'lote_bodega_sugerido': lote_bodega_sugerido,
        'movimientos': movimientos,
        'categorias': categorias,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico solo tiene acceso de consulta al catálogo de medicamentos y no puede gestionar lotes internos de bodega.'
)
def lote_list(request):
    """Lista de lotes con resumen operativo, filtros, ordenamiento FEFO y visualización de cuarentena."""
    query = request.GET.get('q', '')
    ubicacion_id = request.GET.get('ubicacion', '')
    alerta = request.GET.get('alerta', '')
    hoy = date.today()

    if alerta == 'cuarentena':
        lotes = Lote.objects.filter(en_cuarentena=True).select_related(
            'medicamento', 'ubicacion', 'usuario_cuarentena'
        ).order_by('-fecha_cuarentena')
    else:
        lotes = Lote.objects.filter(activo=True, en_cuarentena=False).select_related(
            'medicamento', 'ubicacion'
        ).order_by('fecha_vencimiento')

    if query:
        lotes = lotes.filter(
            Q(numero_lote__icontains=query) |
            Q(medicamento__nombre_generico__icontains=query)
        )
    if ubicacion_id:
        lotes = lotes.filter(ubicacion_id=ubicacion_id)
    if alerta and alerta != 'cuarentena':
        if alerta == 'vencido':
            lotes = lotes.filter(fecha_vencimiento__lte=hoy)
        elif alerta == '30':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hoy + timedelta(days=30))
        elif alerta == '60':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy + timedelta(days=30), fecha_vencimiento__lte=hoy + timedelta(days=60))
        elif alerta == '90':
            lotes = lotes.filter(fecha_vencimiento__gt=hoy + timedelta(days=60), fecha_vencimiento__lte=hoy + timedelta(days=90))

    # Contadores resumen sobre inventario activo fuera de cuarentena
    lotes_activos_base = Lote.objects.filter(activo=True, en_cuarentena=False)
    total_unidades_bodega = (
        lotes_activos_base.filter(
            ubicacion__tipo=Ubicacion.TipoUbicacion.BODEGA,
            fecha_vencimiento__gt=hoy,
        ).aggregate(total=Sum('cantidad_actual'))['total'] or 0
    )
    total_unidades_vitrina = (
        lotes_activos_base.filter(
            ubicacion__tipo=Ubicacion.TipoUbicacion.VITRINA,
            fecha_vencimiento__gt=hoy,
        ).aggregate(total=Sum('cantidad_actual'))['total'] or 0
    )
    lotes_criticos_30 = lotes_activos_base.filter(
        cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy,
        fecha_vencimiento__lte=hoy + timedelta(days=30),
    ).count()
    lotes_vencidos_pendientes = lotes_activos_base.filter(
        cantidad_actual__gt=0,
        fecha_vencimiento__lte=hoy,
    ).count()

    ubicaciones = Ubicacion.objects.filter(activa=True)

    return render(request, 'farmacia/lote_list.html', {
        'lotes': lotes,
        'ubicaciones': ubicaciones,
        'query': query,
        'ubicacion_id': ubicacion_id,
        'alerta': alerta,
        'total_unidades_bodega': total_unidades_bodega,
        'total_unidades_vitrina': total_unidades_vitrina,
        'lotes_criticos_30': lotes_criticos_30,
        'lotes_vencidos_pendientes': lotes_vencidos_pendientes,
    })


@rol_requerido(
    'admin', 'quimico',
    motivo='Solo el Químico Farmacéutico o el Administrador (Docente) están autorizados para retirar lotes vencidos de bodega/vitrina y darlos de baja en Cuarentena.'
)
@transaction.atomic
def lote_cuarentena(request, pk):
    """Retira un lote vencido de Vitrina/Bodega y lo pasa a estado Cuarentena / Baja por Vencimiento."""
    if request.method != 'POST':
        return redirect('farmacia:lote_list')

    lote = get_object_or_404(Lote.objects.select_for_update().select_related('medicamento', 'ubicacion'), pk=pk)
    if lote.en_cuarentena or not lote.activo:
        messages.warning(request, f'El lote {lote.numero_lote} ya se encuentra en Cuarentena / Dado de Baja.')
        return redirect('farmacia:lote_list')

    motivo_ingresado = request.POST.get('motivo', '').strip()
    motivo_final = motivo_ingresado or (
        f'Baja por vencimiento ({lote.fecha_vencimiento.strftime("%d/%m/%Y")}) — Retirado de {lote.ubicacion.nombre}'
    )

    stock_retirado = lote.cantidad_actual
    ubic_origen = lote.ubicacion

    lote.en_cuarentena = True
    lote.activo = False
    lote.cantidad_actual = 0
    lote.motivo_cuarentena = motivo_final
    lote.fecha_cuarentena = timezone.now()
    lote.usuario_cuarentena = request.user
    lote.save()

    MovimientoStock.objects.create(
        lote=lote,
        tipo=MovimientoStock.TipoMovimiento.EGRESO_MERMA,
        cantidad=-stock_retirado,
        cantidad_anterior=stock_retirado,
        cantidad_posterior=0,
        motivo=f'Cuarentena / Baja por Vencimiento: {motivo_final}',
        usuario=request.user,
        ubicacion_origen=ubic_origen,
    )

    if lote.medicamento.es_controlado and stock_retirado > 0:
        from controlados.models import LibroControlados
        LibroControlados.objects.create(
            folio=LibroControlados.siguiente_folio(),
            medicamento=lote.medicamento,
            lote=lote,
            tipo_movimiento=LibroControlados.TipoMovimiento.MERMA,
            cantidad=stock_retirado,
            saldo_anterior=stock_retirado,
            saldo_posterior=0,
            quimico_responsable=request.user,
            verificacion_2fa=True,
            observaciones=f'Baja a Cuarentena: {motivo_final}',
        )

    registrar_auditoria(
        request.user,
        'Retiro y Baja a Cuarentena de Lote Vencido',
        f'Lote {lote.numero_lote} ({lote.medicamento.nombre_generico})',
        valores_anteriores={
            'ubicacion': ubic_origen.nombre,
            'stock_retirado': stock_retirado,
            'estado': 'Vencido Activo',
        },
        valores_nuevos={
            'estado': 'Cuarentena / Baja por Vencimiento',
            'stock_actual': 0,
            'motivo': motivo_final,
        }
    )

    messages.success(
        request,
        f'Lote {lote.numero_lote} ({stock_retirado} unid.) retirado de {ubic_origen.nombre} y pasado a Cuarentena / Baja por Vencimiento.'
    )
    return redirect('farmacia:lote_list')


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para recepcionar ni ingresar lotes al inventario de farmacia.'
)
@transaction.atomic
def lote_crear(request):
    """Registrar un nuevo lote de medicamento con validaciones estrictas FEFO y control ISP."""
    selected_med_id = str(request.POST.get('medicamento') or request.GET.get('medicamento') or '').strip()

    if request.method == 'GET' and selected_med_id.isdigit() and request.user.rol == 'tecnico':
        med_pre = Medicamento.objects.filter(pk=int(selected_med_id)).first()
        if med_pre and med_pre.es_controlado:
            return denegar_acceso(
                request,
                motivo='El ingreso manual de medicamentos controlados (estupefacientes/psicotrópicos ISP) corresponde exclusivamente al Químico Farmacéutico.',
                roles_autorizados=('quimico', 'admin')
            )

    if request.method == 'POST':
        try:
            medicamento = get_object_or_404(Medicamento, pk=request.POST.get('medicamento'))
            if request.user.rol == 'tecnico' and medicamento.es_controlado:
                return denegar_acceso(
                    request,
                    motivo='El ingreso manual de medicamentos controlados (estupefacientes/psicotrópicos ISP) corresponde exclusivamente al Químico Farmacéutico.',
                    roles_autorizados=('quimico', 'admin')
                )

            ubicacion = get_object_or_404(Ubicacion, pk=request.POST.get('ubicacion'))
            numero_lote = request.POST.get('numero_lote', '').strip()
            fecha_fab_str = request.POST.get('fecha_fabricacion', '').strip()
            fecha_venc_str = request.POST.get('fecha_vencimiento', '').strip()
            cantidad = int(request.POST.get('cantidad_inicial', 0) or 0)
            motivo_ingreso = request.POST.get('motivo_ingreso', '').strip()

            if not numero_lote:
                raise ValueError('Debe indicar el número de lote del fabricante.')
            if cantidad <= 0:
                raise ValueError('La cantidad inicial del lote debe ser mayor a cero.')
            if not fecha_fab_str or not fecha_venc_str:
                raise ValueError('Debe ingresar la fecha de fabricación y la fecha de vencimiento.')

            fecha_fab = date.fromisoformat(fecha_fab_str)
            fecha_venc = date.fromisoformat(fecha_venc_str)
            hoy = date.today()

            if fecha_venc <= fecha_fab:
                raise ValueError('La fecha de vencimiento debe ser estrictamente posterior a la fecha de fabricación.')
            if fecha_venc < hoy and ubicacion.tipo == Ubicacion.TipoUbicacion.VITRINA:
                raise ValueError(
                    f'No se puede registrar un lote ya vencido ({fecha_venc.strftime("%d/%m/%Y")}) en {ubicacion.nombre}. '
                    f'Los productos vencidos solo pueden ingresarse en Bodega para cuarentena o verificación técnica.'
                )
            if not motivo_ingreso:
                raise ValueError('Debe indicar el Motivo o N° de Guía / Remesa de respaldo para la trazabilidad.')
            if Lote.objects.filter(
                medicamento=medicamento,
                numero_lote__iexact=numero_lote,
                ubicacion=ubicacion,
            ).exists():
                raise ValueError(
                    f'El lote "{numero_lote}" ya existe para {medicamento.nombre_generico} en {ubicacion.nombre}. '
                    f'No se permite registrar un lote duplicado en la misma ubicación.'
                )

            lote = Lote.objects.create(
                medicamento=medicamento,
                numero_lote=numero_lote,
                fecha_fabricacion=fecha_fab,
                fecha_vencimiento=fecha_venc,
                cantidad_inicial=cantidad,
                cantidad_actual=cantidad,
                ubicacion=ubicacion,
                proveedor=request.POST.get('proveedor', '').strip(),
            )

            MovimientoStock.objects.create(
                lote=lote,
                tipo=MovimientoStock.TipoMovimiento.INGRESO,
                cantidad=cantidad,
                cantidad_anterior=0,
                cantidad_posterior=cantidad,
                motivo=f'Ingreso inicial / Remesa — Lote {lote.numero_lote}: {motivo_ingreso}',
                usuario=request.user,
                ubicacion_destino=ubicacion,
            )

            if medicamento.es_controlado and request.user.rol in ('quimico', 'admin'):
                from controlados.models import LibroControlados
                LibroControlados.objects.create(
                    folio=LibroControlados.siguiente_folio(),
                    medicamento=medicamento,
                    lote=lote,
                    tipo_movimiento=LibroControlados.TipoMovimiento.INGRESO,
                    cantidad=cantidad,
                    saldo_anterior=0,
                    saldo_posterior=cantidad,
                    quimico_responsable=request.user,
                    verificacion_2fa=True,
                    observaciones=f'Ingreso manual ({request.user.get_rol_display()}) lote {lote.numero_lote} — {motivo_ingreso}',
                )

            registrar_auditoria(
                request.user,
                'Ingreso de lote manual',
                f'Lote {lote.numero_lote}',
                valores_nuevos={
                    'medicamento': str(medicamento),
                    'cantidad': cantidad,
                    'ubicacion': ubicacion.nombre,
                    'motivo_guia': motivo_ingreso,
                }
            )

            messages.success(request, f'Lote {lote.numero_lote} registrado correctamente.')
            return redirect('farmacia:lote_list')
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No fue posible registrar el lote: {e}')

    medicamentos = Medicamento.objects.filter(activo=True)
    if request.user.rol == 'tecnico':
        medicamentos = medicamentos.filter(es_controlado=False)
    ubicaciones = Ubicacion.objects.filter(activa=True)
    return render(request, 'farmacia/lote_form.html', {
        'medicamentos': medicamentos,
        'ubicaciones': ubicaciones,
        'selected_med_id': selected_med_id,
        'form_data': request.POST if request.method == 'POST' else {},
        'hoy_iso': date.today().isoformat(),
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El Personal Clínico no está autorizado para consultar el kardex interno de movimientos de bodega.'
)
def movimiento_list(request):
    """Historial de movimientos de stock."""
    movimientos = MovimientoStock.objects.all().select_related(
        'lote', 'lote__medicamento', 'usuario', 'ubicacion_origen', 'ubicacion_destino'
    )[:100]
    return render(request, 'farmacia/movimiento_list.html', {
        'movimientos': movimientos,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='Los traslados operativos entre Bodega y Vitrina solo pueden ser ejecutados por el Técnico en Farmacia, el Químico Farmacéutico o el Administrador (Docente).'
)
@transaction.atomic
def traspaso(request):
    """Traspaso transaccional de stock entre Bodega Central y Vitrina de Dispensación."""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                lote = Lote.objects.select_for_update().select_related('medicamento', 'ubicacion').get(
                    pk=request.POST.get('lote')
                )
                cantidad = int(request.POST.get('cantidad', 0) or 0)
                destino = Ubicacion.objects.get(pk=request.POST.get('destino'))

                if cantidad <= 0:
                    raise ValueError('La cantidad a traspasar debe ser mayor a cero.')
                if lote.ubicacion_id == destino.id:
                    raise ValueError('La ubicación de destino debe ser distinta a la ubicación de origen.')
                if cantidad > lote.cantidad_actual:
                    raise ValueError(f'La cantidad indicada ({cantidad}) supera el stock disponible en el lote ({lote.cantidad_actual}).')
                if lote.esta_vencido:
                    raise ValueError('No se puede traspasar un lote vencido.')

                origen = lote.ubicacion
                cantidad_anterior = lote.cantidad_actual

                lote.cantidad_actual -= cantidad
                lote.save()

                lote_destino, created = Lote.objects.select_for_update().get_or_create(
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
                    motivo=f'Traspaso interno hacia {destino.nombre}',
                    usuario=request.user,
                    ubicacion_origen=origen,
                    ubicacion_destino=destino,
                )

                registrar_auditoria(
                    request.user, 'Traspaso interno de inventario', f'Lote {lote.numero_lote}',
                    valores_anteriores={'ubicacion': str(origen), 'cantidad': cantidad_anterior},
                    valores_nuevos={'ubicacion': str(destino), 'cantidad_traspasada': cantidad}
                )

                messages.success(request, f'Se traspasaron {cantidad} unidades del lote {lote.numero_lote} hacia {destino.nombre}.')
                return redirect('farmacia:movimiento_list')
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'Error en el traspaso: {e}')

    lotes = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0, fecha_vencimiento__gt=date.today()
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')
    ubicaciones = Ubicacion.objects.filter(activa=True)

    selected_lote_id = str(request.POST.get('lote') or request.GET.get('lote') or '').strip()
    if not selected_lote_id and request.GET.get('medicamento', '').isdigit():
        lote_med = lotes.filter(
            medicamento_id=int(request.GET.get('medicamento')),
            ubicacion__tipo=Ubicacion.TipoUbicacion.BODEGA,
            fecha_vencimiento__gt=date.today(),
        ).first()
        if lote_med:
            selected_lote_id = str(lote_med.pk)

    selected_destino_id = str(request.POST.get('destino') or request.GET.get('destino') or '').strip()
    if not selected_destino_id and selected_lote_id.isdigit():
        lote_pre = lotes.filter(pk=int(selected_lote_id)).first()
        if lote_pre:
            tipo_destino = (
                Ubicacion.TipoUbicacion.VITRINA
                if lote_pre.ubicacion.tipo == Ubicacion.TipoUbicacion.BODEGA
                else Ubicacion.TipoUbicacion.BODEGA
            )
            dest_sug = ubicaciones.filter(tipo=tipo_destino).first()
            if dest_sug:
                selected_destino_id = str(dest_sug.pk)

    return render(request, 'farmacia/traspaso.html', {
        'lotes': lotes,
        'ubicaciones': ubicaciones,
        'selected_lote_id': selected_lote_id,
        'selected_destino_id': selected_destino_id,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El monitor de alertas de vencimiento de bodega/vitrina está reservado a Farmacia y Administración.'
)
def alertas_vencimiento(request):
    """Alertas de vencimiento próximo (30/60/90 días) y quiebre de stock."""
    hoy = date.today()

    alertas_30 = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy, fecha_vencimiento__lte=hoy + timedelta(days=30)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    alertas_60 = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy + timedelta(days=30), fecha_vencimiento__lte=hoy + timedelta(days=60)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    alertas_90 = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0,
        fecha_vencimiento__gt=hoy + timedelta(days=60), fecha_vencimiento__lte=hoy + timedelta(days=90)
    ).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento')

    vencidos = Lote.objects.filter(
        activo=True, en_cuarentena=False, cantidad_actual__gt=0, fecha_vencimiento__lte=hoy
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


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El módulo de pedidos y remesas CENABAST no está habilitado para el Personal Clínico.'
)
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

            # 2) Procesar si el usuario incorporó un NUEVO medicamento que no estaba en el catálogo (Solo Admin / Q.F.)
            incluir_nuevo = request.POST.get('incluir_nuevo_med') == 'on'
            nuevo_nombre = request.POST.get('nuevo_nombre_generico', '').strip()
            if incluir_nuevo:
                if request.user.rol not in ('admin', 'quimico'):
                    return denegar_acceso(
                        request,
                        motivo='El Técnico en Farmacia solo puede solicitar medicamentos existentes en el Arsenal Oficial. Solo el Químico Farmacéutico o Administrador puede incorporar fármacos nuevos al catálogo.',
                        roles_autorizados=('quimico', 'admin')
                    )
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

    ordenes_base = OrdenAbastecimiento.objects.all().prefetch_related('detalles', 'detalles__medicamento')
    total_todas = ordenes_base.count()
    total_pendientes_qf = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.PENDIENTE).count()
    total_aprobadas = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.ENVIADA).count()
    total_recepcionadas = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.RECEPCIONADA).count()

    filtro = request.GET.get('filtro', 'todas').strip()
    if filtro == 'pendientes_qf':
        ordenes = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.PENDIENTE)
    elif filtro == 'aprobadas':
        ordenes = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.ENVIADA)
    elif filtro == 'recepcionadas':
        ordenes = ordenes_base.filter(estado=OrdenAbastecimiento.EstadoOrden.RECEPCIONADA)
    else:
        filtro = 'todas'
        ordenes = ordenes_base

    todos_meds = list(Medicamento.objects.filter(activo=True).select_related('categoria'))
    medicamentos_quiebre = [m for m in todos_meds if m.en_quiebre]
    categorias = CategoriaMedicamento.objects.all()

    preselected_med_id = str(request.GET.get('medicamento', '') or '').strip()
    cantidad_sugerida = ''
    if preselected_med_id.isdigit():
        med_pre = next((m for m in todos_meds if str(m.pk) == preselected_med_id), None)
        if med_pre:
            cantidad_sugerida = max(med_pre.stock_maximo - med_pre.stock_total, med_pre.stock_minimo * 3, 100)

    return render(request, 'farmacia/orden_list.html', {
        'ordenes': ordenes,
        'filtro': filtro,
        'total_todas': total_todas,
        'total_pendientes_qf': total_pendientes_qf,
        'total_aprobadas': total_aprobadas,
        'total_recepcionadas': total_recepcionadas,
        'medicamentos': todos_meds,
        'medicamentos_quiebre': medicamentos_quiebre,
        'categorias': categorias,
        'preselected_med_id': preselected_med_id,
        'cantidad_sugerida': cantidad_sugerida,
    })


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='La generación de borradores de abastecimiento CENABAST no está habilitada para el Personal Clínico.'
)
@transaction.atomic
def generar_orden_automatica(request):
    """
    Detecta todos los fármacos en quiebre de stock (bajo stock_minimo) o con stock crítico
    y genera una Orden de Pedido en estado PENDIENTE (Borrador Editable), evitando duplicados
    si ya existe un borrador con los mismos medicamentos en quiebre.
    """
    todos_meds = list(Medicamento.objects.filter(activo=True))
    meds_criticos = [m for m in todos_meds if m.en_quiebre]

    if not meds_criticos:
        meds_criticos = sorted(todos_meds, key=lambda m: m.stock_total)[:2]

    ids_criticos = sorted(m.pk for m in meds_criticos)
    ordenes_pendientes = OrdenAbastecimiento.objects.filter(
        estado=OrdenAbastecimiento.EstadoOrden.PENDIENTE
    ).prefetch_related('detalles')
    for ord_pend in ordenes_pendientes:
        ids_ord = sorted(ord_pend.detalles.values_list('medicamento_id', flat=True))
        if ids_ord == ids_criticos:
            messages.warning(
                request,
                f'Ya existe una propuesta en borrador ({ord_pend.numero_orden}) con los mismos fármacos en quiebre. '
                f'Puedes revisarla, editarla o aprobarla directamente.'
            )
            return redirect('farmacia:orden_detalle', pk=ord_pend.pk)

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


@rol_requerido(
    'admin', 'quimico', 'tecnico',
    motivo='El módulo de órdenes de abastecimiento CENABAST no está habilitado para el Personal Clínico.'
)
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

        # 1. Editar datos generales de la cabecera (solo en Borrador)
        if accion == 'editar_cabecera' and orden.estado == OrdenAbastecimiento.EstadoOrden.PENDIENTE:
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

        # 2. Actualizar la cantidad solicitada de un ítem específico (solo en Borrador)
        elif accion == 'actualizar_item' and orden.estado == OrdenAbastecimiento.EstadoOrden.PENDIENTE:
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

        # 3. Eliminar un ítem de la orden (solo en Borrador)
        elif accion == 'eliminar_item' and orden.estado == OrdenAbastecimiento.EstadoOrden.PENDIENTE:
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

        # 4. Agregar un medicamento existente del catálogo a la orden (solo en Borrador)
        elif accion == 'agregar_item_existente' and orden.estado == OrdenAbastecimiento.EstadoOrden.PENDIENTE:
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

        # 5. Crear un NUEVO medicamento que no existe en el catálogo y agregarlo a la orden (Solo Admin / Q.F. en Borrador)
        elif accion == 'agregar_item_nuevo' and orden.estado == OrdenAbastecimiento.EstadoOrden.PENDIENTE:
            if request.user.rol not in ('admin', 'quimico'):
                return denegar_acceso(
                    request,
                    motivo='El Técnico en Farmacia solo puede solicitar medicamentos existentes en el Arsenal Oficial. Solo el Químico Farmacéutico o Administrador puede incorporar fármacos nuevos.',
                    roles_autorizados=('quimico', 'admin')
                )
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

        # 6. Reabrir orden a estado Pendiente (Borrador) — limpia firma Q.F. previa para exigir nueva visación
        elif accion == 'reabrir_edicion' and orden.estado != OrdenAbastecimiento.EstadoOrden.RECEPCIONADA:
            est_ant = orden.estado
            orden.estado = OrdenAbastecimiento.EstadoOrden.PENDIENTE
            orden.aprobador_qf = None
            orden.save()
            registrar_auditoria(
                request.user,
                'Reapertura de Orden CENABAST a Borrador',
                f'Orden {orden.numero_orden}',
                valores_anteriores={'estado': est_ant},
                valores_nuevos={'estado': 'pendiente', 'visacion_qf': 'pendiente'}
            )
            messages.info(request, f'Orden {orden.numero_orden} reabierta en estado Borrador. Requerirá nueva aprobación Q.F. antes de recepcionar.')
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

        # 9. Visar / Aprobar como Q.F. (o simulación de despacho por Admin)
        elif accion == 'aprobar':
            if request.user.rol not in ('admin', 'quimico'):
                return denegar_acceso(
                    request,
                    motivo='El Técnico en Farmacia puede levantar borradores de reposición, pero la aprobación oficial requiere la validación del Químico Farmacéutico.',
                    roles_autorizados=('quimico', 'admin')
                )
            if orden.estado != OrdenAbastecimiento.EstadoOrden.PENDIENTE:
                messages.warning(request, 'Solo las órdenes en estado Borrador / Pendiente Q.F. pueden aprobarse.')
                return redirect('farmacia:orden_detalle', pk=orden.pk)
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
            messages.success(request, f'Orden {orden.numero_orden} aprobada por Q.F. y habilitada para recepción en Bodega.')
            return redirect('farmacia:orden_detalle', pk=orden.pk)

        # 10. Recepcionar remesa en Bodega Central (BLOQUEADO sin aprobación oficial previa del Q.F.)
        elif accion == 'recepcionar':
            if orden.estado != OrdenAbastecimiento.EstadoOrden.ENVIADA or not orden.aprobador_qf:
                registrar_auditoria(
                    request.user,
                    'Intento Bloqueado de Recepción sin Visación Q.F.',
                    f'Orden {orden.numero_orden}',
                    valores_nuevos={'estado_actual': orden.estado, 'rol': request.user.rol}
                )
                return denegar_acceso(
                    request,
                    motivo='La recepción de remesa e ingreso de stock a Bodega están bloqueados hasta que la orden cuente con aprobación oficial del Químico Farmacéutico.',
                    roles_autorizados=('quimico',)
                )
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
