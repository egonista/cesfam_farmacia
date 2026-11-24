# Generated manually to ensure Folio #3 (Morfina) is signed by the Q.F. (qf_suazo) rather than Admin.
from django.db import migrations


def corregir_qf_folio_3(apps, schema_editor):
    LibroControlados = apps.get_model('controlados', 'LibroControlados')
    Usuario = apps.get_model('core', 'Usuario')
    qf = Usuario.objects.filter(username='qf_suazo').first() or Usuario.objects.filter(rol='quimico').first()
    if qf:
        LibroControlados.objects.filter(folio=3, quimico_responsable__rol='admin').update(quimico_responsable=qf)


def revertir_qf_folio_3(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('controlados', '0002_initial'),
    ]

    operations = [
        migrations.RunPython(corregir_qf_folio_3, revertir_qf_folio_3),
    ]
