# Generated manually to populate initial section/course values for base users.
from django.db import migrations


def poblar_secciones_base(apps, schema_editor):
    Usuario = apps.get_model('core', 'Usuario')
    mapeo = {
        'admin': 'Docencia',
        'qf_suazo': 'AP-N4-C1',
        'tecnico_alvarez': 'AP-N4-C1',
        'enfermera_gonzalez': 'AP-N4-C1',
    }
    for username, seccion in mapeo.items():
        Usuario.objects.filter(username=username, seccion='').update(seccion=seccion)


def revertir_secciones_base(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_usuario_seccion'),
    ]

    operations = [
        migrations.RunPython(poblar_secciones_base, revertir_secciones_base),
    ]
