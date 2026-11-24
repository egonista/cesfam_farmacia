"""
Migración de datos: diferencia claramente los 2 escenarios iniciales de ejemplo
('Escenario Base' con el padrón completo vs 'Evaluación 1' con 3 pacientes y 2 recetas).
"""
from django.db import migrations
from django.utils import timezone


def diferenciar_escenarios(apps, schema_editor):
    EscenarioSimulacion = apps.get_model('core', 'EscenarioSimulacion')
    Paciente = apps.get_model('core', 'Paciente')
    Receta = apps.get_model('dispensacion', 'Receta')
    DetalleReceta = apps.get_model('dispensacion', 'DetalleReceta')

    if not Paciente.objects.exists() and not Receta.objects.exists():
        return

    esc_base = EscenarioSimulacion.objects.filter(
        nombre='Escenario Base — Operación General CESFAM'
    ).first()
    if esc_base:
        esc_base.pacientes.set(Paciente.objects.all())
        esc_base.recetas.set(Receta.objects.all())
        esc_base.actualizado_en = timezone.now()
        esc_base.save(update_fields=['actualizado_en'])

    esc_eval = EscenarioSimulacion.objects.filter(
        nombre='Evaluación 1 — Crónicos GES y Controlados ISP'
    ).first()
    if esc_eval:
        ruts_eval = ['8.765.432-K', '7.654.321-6', '9.876.543-3']
        pacientes_eval = list(Paciente.objects.filter(rut__in=ruts_eval))
        if not pacientes_eval:
            pacientes_eval = list(Paciente.objects.filter(cronico=True).order_by('id')[:3])

        nums_eval = ['REC-2026-00104', 'REC-2026-00105']
        recetas_eval = list(Receta.objects.filter(numero_receta__in=nums_eval))
        if not recetas_eval:
            recetas_eval = list(
                Receta.objects.filter(paciente_id__in=[p.id for p in pacientes_eval]).order_by('-id')[:2]
            )

        esc_eval.pacientes.set(pacientes_eval)
        esc_eval.recetas.set(recetas_eval)
        esc_eval.actualizado_en = timezone.now()
        esc_eval.save(update_fields=['actualizado_en'])

        # Si ninguna de las recetas de Evaluación 1 está pendiente, restaurarlas para pruebas inmediatas en Ventanilla
        rec_ids = [r.id for r in recetas_eval]
        if rec_ids and not Receta.objects.filter(id__in=rec_ids, estado__in=['pendiente', 'parcial']).exists():
            DetalleReceta.objects.filter(receta_id__in=rec_ids).update(cantidad_dispensada=0)
            Receta.objects.filter(id__in=rec_ids).update(
                estado='pendiente',
                autorizada_qf=False,
                qf_autorizador=None,
                fecha_autorizacion_qf=None,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_escenariosimulacion_actualizado_en_and_more'),
    ]

    operations = [
        migrations.RunPython(diferenciar_escenarios, reverse_code=noop_reverse),
    ]
