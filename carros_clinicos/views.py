"""
Vistas del módulo Carros Clínicos del Sistema CESFAM Farmacia.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from .models import CarroClinico, PlantillaItemCarro, ConsumoCarroClinico, ReposicionCarro
from farmacia.models import Lote, MovimientoStock
from core.utils import registrar_auditoria


@login_required
def carro_list(request):
    """Lista de carros clínicos."""
    carros = CarroClinico.objects.filter(activo=True).prefetch_related('plantilla_items')
    return render(request, 'carros_clinicos/carro_list.html', {'carros': carros})


@login_required
def carro_detalle(request, pk):
    """Detalle de un carro clínico con plantilla canónica."""
    carro = get_object_or_404(CarroClinico, pk=pk)
    items = carro.plantilla_items.all().select_related('medicamento')
    consumos_recientes = carro.consumos.all().order_by('-fecha')[:20]
    reposiciones_recientes = carro.reposiciones.all().order_by('-fecha')[:20]

    return render(request, 'carros_clinicos/carro_detalle.html', {
        'carro': carro,
        'items': items,
        'consumos_recientes': consumos_recientes,
        'reposiciones_recientes': reposiciones_recientes,
    })


@login_required
@transaction.atomic
def registrar_consumo(request, pk):
    """Registrar consumo de medicamentos del carro en emergencia."""
    carro = get_object_or_404(CarroClinico, pk=pk)

    if request.method == 'POST':
        try:
            item = PlantillaItemCarro.objects.get(pk=request.POST.get('item'))
            cantidad = int(request.POST.get('cantidad', 0))

            if cantidad > item.cantidad_actual:
                messages.error(request, 'Cantidad excede el stock del carro.')
                return redirect('carros_clinicos:carro_detalle', pk=pk)

            ConsumoCarroClinico.objects.create(
                carro=carro,
                item=item,
                cantidad_consumida=cantidad,
                motivo=request.POST.get('motivo', ''),
                paciente_atendido=request.POST.get('paciente_atendido', ''),
                personal_clinico=request.user,
            )

            item.cantidad_actual -= cantidad
            item.save()

            # Actualizar estado del carro
            if not carro.esta_completo:
                carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
                carro.save()

            registrar_auditoria(
                request.user,
                'Consumo en carro clínico',
                f'Carro: {carro.nombre}',
                valores_nuevos={
                    'medicamento': item.medicamento.nombre_generico,
                    'cantidad_consumida': cantidad,
                    'motivo': request.POST.get('motivo', ''),
                }
            )

            messages.success(request, f'Consumo registrado: {item.medicamento.nombre_generico} x{cantidad}.')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return redirect('carros_clinicos:carro_detalle', pk=pk)


@login_required
@transaction.atomic
def reponer_carro(request, pk):
    """Reponer medicamentos del carro desde farmacia (FEFO)."""
    carro = get_object_or_404(CarroClinico, pk=pk)

    if not request.user.tiene_permiso_dispensacion():
        messages.error(request, 'No tiene permisos para reponer carros.')
        return redirect('carros_clinicos:carro_detalle', pk=pk)

    if request.method == 'POST':
        try:
            item = PlantillaItemCarro.objects.get(pk=request.POST.get('item'))
            lote = Lote.objects.select_for_update().get(pk=request.POST.get('lote'))
            cantidad = int(request.POST.get('cantidad', 0))
            nuevo_precinto = request.POST.get('nuevo_precinto', '')

            if cantidad > lote.cantidad_actual:
                messages.error(request, 'Stock insuficiente en el lote seleccionado.')
                return redirect('carros_clinicos:carro_detalle', pk=pk)

            # Descontar del lote
            cantidad_anterior = lote.cantidad_actual
            lote.cantidad_actual -= cantidad
            lote.save()

            # Reponer en el carro
            item.cantidad_actual += cantidad
            item.save()

            # Registrar movimiento de stock
            MovimientoStock.objects.create(
                lote=lote,
                tipo=MovimientoStock.TipoMovimiento.EGRESO_CARRO,
                cantidad=-cantidad,
                cantidad_anterior=cantidad_anterior,
                cantidad_posterior=lote.cantidad_actual,
                motivo=f'Reposición carro {carro.nombre}',
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

            # Actualizar precinto y estado
            if nuevo_precinto:
                carro.numero_precinto = nuevo_precinto
                carro.fecha_ultimo_precinto = timezone.now()

            if carro.esta_completo:
                carro.estado = CarroClinico.EstadoCarro.COMPLETO
            carro.save()

            registrar_auditoria(
                request.user,
                'Reposición de carro clínico',
                f'Carro: {carro.nombre}',
                valores_nuevos={
                    'medicamento': item.medicamento.nombre_generico,
                    'cantidad_repuesta': cantidad,
                    'lote': lote.numero_lote,
                    'precinto': nuevo_precinto,
                }
            )

            messages.success(request, f'Reposición completada. Precinto: {nuevo_precinto}.')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return redirect('carros_clinicos:carro_detalle', pk=pk)
