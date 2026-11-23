"""
Vistas del módulo GES/AUGE del Sistema CESFAM Farmacia.
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Sum
from django.shortcuts import render, redirect, get_object_or_404

from .models import PatologiaGES, CanastaGES, InscripcionGES, CuotaGES
from core.models import Paciente


@login_required
def inscripcion_list(request):
    """Lista de inscripciones GES con búsqueda."""
    query = request.GET.get('q', '')
    inscripciones = InscripcionGES.objects.filter(
        activa=True
    ).select_related('paciente', 'patologia')

    if query:
        inscripciones = inscripciones.filter(
            Q(paciente__rut__icontains=query) |
            Q(paciente__apellido_paterno__icontains=query) |
            Q(patologia__nombre__icontains=query)
        )

    return render(request, 'ges/inscripcion_list.html', {
        'inscripciones': inscripciones,
        'query': query,
    })


@login_required
def inscripcion_detalle(request, pk):
    """Detalle de inscripción GES con saldo de cuotas."""
    inscripcion = get_object_or_404(
        InscripcionGES.objects.select_related('paciente', 'patologia'),
        pk=pk
    )
    canastas = CanastaGES.objects.filter(patologia=inscripcion.patologia)

    # Para cada canasta, calcular cuotas usadas y saldo
    canastas_info = []
    for canasta in canastas:
        cuotas_usadas = CuotaGES.objects.filter(
            inscripcion=inscripcion,
            canasta=canasta,
        ).count()
        canastas_info.append({
            'canasta': canasta,
            'cuotas_usadas': cuotas_usadas,
            'cuotas_restantes': canasta.cuotas_autorizadas - cuotas_usadas,
            'tiene_saldo': cuotas_usadas < canasta.cuotas_autorizadas,
        })

    return render(request, 'ges/inscripcion_detalle.html', {
        'inscripcion': inscripcion,
        'canastas_info': canastas_info,
    })


@login_required
def verificar_ges(request, paciente_pk):
    """Verificación automática de patología GES activa para un paciente."""
    paciente = get_object_or_404(Paciente, pk=paciente_pk)
    inscripciones = InscripcionGES.objects.filter(
        paciente=paciente, activa=True
    ).select_related('patologia')

    resultados = []
    for insc in inscripciones:
        canastas = CanastaGES.objects.filter(patologia=insc.patologia)
        for canasta in canastas:
            cuotas_usadas = CuotaGES.objects.filter(
                inscripcion=insc, canasta=canasta
            ).count()
            resultados.append({
                'patologia': insc.patologia.nombre,
                'medicamento': canasta.medicamento.nombre_generico,
                'cuotas_autorizadas': canasta.cuotas_autorizadas,
                'cuotas_usadas': cuotas_usadas,
                'cuotas_restantes': canasta.cuotas_autorizadas - cuotas_usadas,
                'puede_despachar': cuotas_usadas < canasta.cuotas_autorizadas,
            })

    return render(request, 'ges/verificar_ges.html', {
        'paciente': paciente,
        'resultados': resultados,
    })
