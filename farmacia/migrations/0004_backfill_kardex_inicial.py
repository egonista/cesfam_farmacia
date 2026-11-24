"""
Migración de datos: garantiza un movimiento inicial en el Kardex (MovimientoStock)
para los lotes precargados del seed o existentes que aún no posean asiento de ingreso.
"""
from django.db import migrations


def backfill_kardex_inicial(apps, schema_editor):
    Lote = apps.get_model('farmacia', 'Lote')
    MovimientoStock = apps.get_model('farmacia', 'MovimientoStock')
    Usuario = apps.get_model('core', 'Usuario')

    operador = (
        Usuario.objects.filter(rol='quimico').order_by('id').first()
        or Usuario.objects.filter(rol='admin').order_by('id').first()
        or Usuario.objects.order_by('id').first()
    )
    if not operador:
        return

    for lote in Lote.objects.select_related('ubicacion').all():
        if not MovimientoStock.objects.filter(lote=lote).exists():
            MovimientoStock.objects.create(
                lote=lote,
                tipo='ingreso',
                cantidad=lote.cantidad_inicial,
                cantidad_anterior=0,
                cantidad_posterior=lote.cantidad_inicial,
                motivo=f'Ingreso inicial / Remesa CENABAST — Lote {lote.numero_lote}',
                usuario=operador,
                ubicacion_destino=lote.ubicacion,
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('farmacia', '0003_lote_en_cuarentena_lote_fecha_cuarentena_and_more'),
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_kardex_inicial, reverse_code=noop_reverse),
    ]
