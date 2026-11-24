"""
Migración de datos: unifica categorías respiratorias duplicadas en
'Respiratorio / Broncodilatadores (GES Asma/EPOC)'.
"""
from django.db import migrations


def unificar_categoria_respiratorio(apps, schema_editor):
    CategoriaMedicamento = apps.get_model('farmacia', 'CategoriaMedicamento')
    Medicamento = apps.get_model('farmacia', 'Medicamento')

    nombre_oficial = 'Respiratorio / Broncodilatadores (GES Asma/EPOC)'
    nombre_duplicado = 'Respiratorio / Broncodilatadores'

    cat_duplicada = CategoriaMedicamento.objects.filter(nombre=nombre_duplicado).first()
    if not cat_duplicada:
        return

    cat_oficial, _ = CategoriaMedicamento.objects.get_or_create(
        nombre=nombre_oficial,
        defaults={
            'descripcion': cat_duplicada.descripcion or 'Tratamiento de crisis bronquiales y asma/EPOC',
            'es_controlado': False,
        },
    )
    Medicamento.objects.filter(categoria=cat_duplicada).update(categoria=cat_oficial)
    cat_duplicada.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('farmacia', '0004_backfill_kardex_inicial'),
    ]

    operations = [
        migrations.RunPython(unificar_categoria_respiratorio, reverse_code=noop_reverse),
    ]
