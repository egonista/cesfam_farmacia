"""
Migración de datos: crea los 2 escenarios iniciales de simulación docente
cuando la base de datos ya cuenta con pacientes o recetas cargadas.
"""
from datetime import date
from django.db import migrations


def crear_escenarios_iniciales(apps, schema_editor):
    EscenarioSimulacion = apps.get_model('core', 'EscenarioSimulacion')
    Paciente = apps.get_model('core', 'Paciente')
    Usuario = apps.get_model('core', 'Usuario')
    Receta = apps.get_model('dispensacion', 'Receta')
    InscripcionGES = apps.get_model('ges', 'InscripcionGES')

    if not Paciente.objects.exists() and not Receta.objects.exists():
        return

    admin_usr = Usuario.objects.filter(rol='admin').order_by('id').first()
    hoy = date.today()

    hay_activo = EscenarioSimulacion.objects.filter(activo=True).exists()
    esc_base, _ = EscenarioSimulacion.objects.get_or_create(
        nombre='Escenario Base — Operación General CESFAM',
        defaults={
            'descripcion': 'Operación general completa del CESFAM con todo el padrón de pacientes y recetas disponibles.',
            'activo': not hay_activo,
            'creado_por': admin_usr,
        },
    )
    esc_base.pacientes.set(Paciente.objects.all())
    esc_base.recetas.set(Receta.objects.all())

    esc_eval, _ = EscenarioSimulacion.objects.get_or_create(
        nombre='Evaluación 1 — Crónicos GES y Controlados ISP',
        defaults={
            'descripcion': 'Taller evaluado focalizado en pacientes crónicos/GES y dispensación de recetas vigentes y controladas (D.S. 404/405).',
            'activo': False,
            'creado_por': admin_usr,
        },
    )

    pacientes_ges_ids = set(
        InscripcionGES.objects.filter(activa=True).values_list('paciente_id', flat=True)
    )
    pacientes_cronicos_ids = set(
        Paciente.objects.filter(cronico=True).values_list('id', flat=True)
    )
    pacientes_eval_ids = pacientes_ges_ids | pacientes_cronicos_ids

    recetas_vigentes_ids = []
    for r in Receta.objects.exclude(estado__in=['anulada', 'vencida']):
        if r.fecha_vencimiento >= hoy and (
            r.tipo == 'cronica' or (hoy - r.fecha_emision).days <= 30
        ):
            recetas_vigentes_ids.append(r.id)
            pacientes_eval_ids.add(r.paciente_id)

    esc_eval.pacientes.set(Paciente.objects.filter(id__in=pacientes_eval_ids))
    esc_eval.recetas.set(Receta.objects.filter(id__in=recetas_vigentes_ids))


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_paciente_tercero_autorizado_nombre_and_more'),
        ('dispensacion', '0002_receta_autorizada_qf_receta_fecha_autorizacion_qf_and_more'),
        ('ges', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_escenarios_iniciales, reverse_code=noop_reverse),
    ]
