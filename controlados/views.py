"""
Vistas del módulo Controlados del Sistema CESFAM Farmacia.
Libro Oficial Digital de Estupefacientes y Psicotrópicos (D.S. 404/405).
"""
import pyotp
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect

from .models import LibroControlados
from farmacia.models import Medicamento, Lote
from core.utils import registrar_auditoria


@login_required
def libro(request):
    """Vista del Libro Oficial Digital de Controlados."""
    if not request.user.tiene_permiso_controlados():
        messages.error(request, 'Solo Químicos Farmacéuticos pueden acceder al Libro de Controlados.')
        return redirect('core:dashboard')

    registros = LibroControlados.objects.all().select_related(
        'medicamento', 'lote', 'receta', 'paciente', 'quimico_responsable'
    )[:100]

    medicamentos_controlados = Medicamento.objects.filter(es_controlado=True, activo=True)

    return render(request, 'controlados/libro.html', {
        'registros': registros,
        'medicamentos_controlados': medicamentos_controlados,
    })


@login_required
def registro_controlado(request):
    """Registrar movimiento en el Libro de Controlados con verificación 2FA."""
    if not request.user.tiene_permiso_controlados():
        messages.error(request, 'No tiene permisos para esta operación.')
        return redirect('core:dashboard')

    if request.method == 'POST':
        # Verificar 2FA (PIN de seguridad simulado)
        pin_ingresado = request.POST.get('pin_2fa', '')
        pin_valido = False

        if request.user.pin_seguridad:
            from django.contrib.auth.hashers import check_password
            pin_valido = check_password(pin_ingresado, request.user.pin_seguridad)
        elif request.user.totp_secret:
            totp = pyotp.TOTP(request.user.totp_secret)
            pin_valido = totp.verify(pin_ingresado)
        else:
            # Si no tiene 2FA configurado, aceptar PIN '123456' (simulado)
            pin_valido = pin_ingresado == '123456'

        if not pin_valido:
            messages.error(request, 'Verificación de segundo factor fallida. Operación denegada.')
            return redirect('controlados:libro')

        try:
            medicamento = Medicamento.objects.get(pk=request.POST.get('medicamento'))
            lote = Lote.objects.get(pk=request.POST.get('lote'))
            tipo = request.POST.get('tipo_movimiento')
            cantidad = int(request.POST.get('cantidad', 0))

            saldo_anterior = lote.cantidad_actual
            if tipo == 'ingreso':
                lote.cantidad_actual += cantidad
                saldo_posterior = lote.cantidad_actual
            else:
                if cantidad > lote.cantidad_actual:
                    messages.error(request, 'Stock insuficiente para el egreso.')
                    return redirect('controlados:libro')
                lote.cantidad_actual -= cantidad
                saldo_posterior = lote.cantidad_actual
            lote.save()

            registro = LibroControlados.objects.create(
                folio=LibroControlados.siguiente_folio(),
                medicamento=medicamento,
                lote=lote,
                tipo_movimiento=tipo,
                cantidad=cantidad,
                saldo_anterior=saldo_anterior,
                saldo_posterior=saldo_posterior,
                quimico_responsable=request.user,
                verificacion_2fa=True,
                observaciones=request.POST.get('observaciones', ''),
            )

            # Auditoría en MongoDB
            registrar_auditoria(
                request.user,
                f'Registro controlado - {tipo}',
                f'Libro Controlados Folio {registro.folio}',
                valores_anteriores={'saldo': saldo_anterior},
                valores_nuevos={'saldo': saldo_posterior, 'cantidad': cantidad},
            )

            messages.success(request, f'Registro folio #{registro.folio} creado exitosamente.')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return redirect('controlados:libro')


@login_required
def verificar_2fa(request):
    """Endpoint AJAX para verificar 2FA."""
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
