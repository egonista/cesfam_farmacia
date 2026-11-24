# Generated manually to fix duplicated concentration text on INS-CLI-001 (Suero Fisiológico NaCl).
from django.db import migrations


def corregir_suero_fisiologico(apps, schema_editor):
    Medicamento = apps.get_model('farmacia', 'Medicamento')
    Medicamento.objects.filter(codigo='INS-CLI-001').update(
        nombre_generico='Suero Fisiológico NaCl',
        concentracion='0,9% (500 ml)',
    )


def revertir_suero_fisiologico(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('farmacia', '0005_unificar_categoria_respiratorio'),
    ]

    operations = [
        migrations.RunPython(corregir_suero_fisiologico, revertir_suero_fisiologico),
    ]
