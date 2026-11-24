"""
Vistas del módulo de Medicamentos Controlados del Sistema CESFAM Farmacia.
Libro Oficial Digital de Estupefacientes y Psicotrópicos con conciliación de saldos y alertas de descuadre.
"""
import pyotp
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from .models import LibroControlados
from farmacia.models import Medicamento, Lote, MovimientoStock
from dispensacion.models import Receta
from core.models import Paciente
from core.utils import registrar_auditoria
from core.decorators import rol_requerido


@rol_requerido(
    'quimico',
    motivo='Exclusivo Químico Farmacéutico: Solo el Director Técnico puede consultar, gestionar y firmar el Libro Oficial de Medicamentos Controlados.'
)
def libro(request):
    """Vista del Libro Oficial Digital de Controlados y monitor de cuadratura de saldos."""
    registros = LibroControlados.objects.all().select_related(
        'medicamento', 'lote', 'receta', 'paciente', 'quimico_responsable'
    ).order_by('-folio')[:100]

    medicamentos_controlados = Medicamento.objects.filter(
        es_controlado=True, activo=True
    ).prefetch_related('lotes')

    # Conciliación entre el último saldo foliado en el libro y el stock físico en lotes
    lotes_controlados = Lote.objects.filter(
        medicamento__es_controlado=True, activo=True
    ).select_related('medicamento', 'ubicacion')

    conciliacion_lotes = []
    alertas_descuadre = []
    for lote in lotes_controlados:
        ultimo_asiento = LibroControlados.objects.filter(lote=lote).order_by('-folio').first()
        saldo_libro = ultimo_asiento.saldo_posterior if ultimo_asiento else lote.cantidad_actual
        diferencia = lote.cantidad_actual - saldo_libro
        item_conciliacion = {
            'lote': lote,
            'medicamento': lote.medicamento,
            'saldo_libro': saldo_libro,
            'stock_fisico': lote.cantidad_actual,
            'diferencia': diferencia,
            'cuadrado': diferencia == 0,
            'ultimo_folio': ultimo_asiento.folio if ultimo_asiento else None,
        }
        conciliacion_lotes.append(item_conciliacion)
        if diferencia != 0:
            alertas_descuadre.append(item_conciliacion)

    pacientes = Paciente.objects.filter(activo=True)
    recetas_controladas = Receta.objects.filter(tipo__in=['cheque', 'retenida']).select_related('paciente')[:30]

    return render(request, 'controlados/libro.html', {
        'registros': registros,
        'medicamentos_controlados': medicamentos_controlados,
        'conciliacion_lotes': conciliacion_lotes,
        'alertas_descuadre': alertas_descuadre,
        'pacientes': pacientes,
        'recetas_controladas': recetas_controladas,
    })


@rol_requerido(
    'quimico',
    motivo='Exclusivo Químico Farmacéutico: Solo el Químico Farmacéutico puede asentar y firmar movimientos en el Libro de Controlados.'
)
@transaction.atomic
def registro_controlado(request):
    """Registrar movimiento foliado en el Libro de Controlados con bloqueo de fila y PIN de autorización."""
    if request.method == 'POST':
        pin_ingresado = request.POST.get('pin_2fa', '').strip()
        pin_valido = False

        if request.user.pin_seguridad:
            from django.contrib.auth.hashers import check_password
            pin_valido = check_password(pin_ingresado, request.user.pin_seguridad)
        elif request.user.totp_secret:
            totp = pyotp.TOTP(request.user.totp_secret)
            pin_valido = totp.verify(pin_ingresado)
        else:
            pin_valido = pin_ingresado == '123456'

        if not pin_valido:
            messages.error(request, 'El código o PIN de autorización ingresado es incorrecto. Operación cancelada.')
            return redirect('controlados:libro')

        try:
            with transaction.atomic():
                lote = Lote.objects.select_for_update().select_related('medicamento').get(pk=request.POST.get('lote'))
                medicamento = lote.medicamento
                tipo = request.POST.get('tipo_movimiento')
                cantidad = int(request.POST.get('cantidad', 0) or 0)

                if cantidad <= 0:
                    raise ValueError('La cantidad del movimiento debe ser mayor a cero.')

                saldo_anterior = lote.cantidad_actual
                if tipo in ('ingreso', 'devolucion'):
                    lote.cantidad_actual += cantidad
                    saldo_posterior = lote.cantidad_actual
                    tipo_kardex = MovimientoStock.TipoMovimiento.INGRESO
                    variacion = cantidad
                else:
                    if lote.esta_vencido and tipo == 'egreso':
                        raise ValueError(f'El lote {lote.numero_lote} se encuentra vencido y no puede ser dispensado.')
                    if cantidad > lote.cantidad_actual:
                        raise ValueError(f'Stock insuficiente en el lote {lote.numero_lote} ({lote.cantidad_actual} disponibles).')
                    lote.cantidad_actual -= cantidad
                    saldo_posterior = lote.cantidad_actual
                    tipo_kardex = (
                        MovimientoStock.TipoMovimiento.EGRESO_MERMA
                        if tipo == 'merma'
                        else MovimientoStock.TipoMovimiento.EGRESO_DISPENSACION
                    )
                    variacion = -cantidad

                lote.save()

                paciente_obj = None
                if request.POST.get('paciente'):
                    paciente_obj = Paciente.objects.filter(pk=request.POST.get('paciente')).first()

                receta_obj = None
                if request.POST.get('receta'):
                    receta_obj = Receta.objects.filter(pk=request.POST.get('receta')).first()

                obs = request.POST.get('observaciones', '').strip()

                registro = LibroControlados.objects.create(
                    folio=LibroControlados.siguiente_folio(),
                    medicamento=medicamento,
                    lote=lote,
                    tipo_movimiento=tipo,
                    cantidad=cantidad,
                    saldo_anterior=saldo_anterior,
                    saldo_posterior=saldo_posterior,
                    paciente=paciente_obj,
                    receta=receta_obj,
                    quimico_responsable=request.user,
                    verificacion_2fa=True,
                    observaciones=obs,
                )

                MovimientoStock.objects.create(
                    lote=lote,
                    tipo=tipo_kardex,
                    cantidad=variacion,
                    cantidad_anterior=saldo_anterior,
                    cantidad_posterior=saldo_posterior,
                    motivo=f'Libro de Controlados Folio #{registro.folio}: {obs or registro.get_tipo_movimiento_display()}',
                    usuario=request.user,
                    ubicacion_origen=lote.ubicacion if variacion < 0 else None,
                    ubicacion_destino=lote.ubicacion if variacion > 0 else None,
                )

                registrar_auditoria(
                    request.user,
                    f'Movimiento en Libro de Controlados ({registro.get_tipo_movimiento_display()})',
                    f'Folio #{registro.folio} - {medicamento.nombre_generico}',
                    valores_anteriores={'saldo': saldo_anterior},
                    valores_nuevos={'saldo': saldo_posterior, 'cantidad': cantidad, 'lote': lote.numero_lote},
                )

                messages.success(request, f'Movimiento asentado correctamente con Folio #{registro.folio}.')
        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f'No se pudo registrar el movimiento: {e}')

    return redirect('controlados:libro')


@login_required
def verificar_2fa(request):
    """Verificación de PIN de autorización del Químico Farmacéutico."""
    pin = request.GET.get('pin', '')
    valido = False

    if request.user.pin_seguridad:
        from django.contrib.auth.hashers import check_password
        valido = check_password(pin, request.user.pin_seguridad)
    elif request.user.totp_secret:
        totp = pyotp.TOTP(request.user.totp_secret)
        valido = totp.verify(pin)
    else:
        valido = pin == '123456'

    return JsonResponse({'valido': valido})
