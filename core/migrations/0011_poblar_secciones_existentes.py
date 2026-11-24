# Generated manually to populate SeccionCurso from existing users and base sections.
from django.db import migrations


def poblar_secciones_existentes(apps, schema_editor):
    SeccionCurso = apps.get_model('core', 'SeccionCurso')
    Usuario = apps.get_model('core', 'Usuario')

    descripciones_base = {
        'docencia': 'Equipo docente y coordinación del simulador CESFAM',
        'ap-n4-c1': 'Sección base de simulación clínica INACAP',
    }

    # 1. Asegurar secciones base
    for nombre_base in ('Docencia', 'AP-N4-C1'):
        if not SeccionCurso.objects.filter(nombre__iexact=nombre_base).exists():
            SeccionCurso.objects.create(
                nombre=nombre_base,
                descripcion=descripciones_base.get(nombre_base.lower(), ''),
                activa=True,
            )

    # 2. Incorporar cualquier otra sección existente en los usuarios actuales
    secciones_usuarios = (
        Usuario.objects.exclude(seccion='')
        .exclude(seccion__isnull=True)
        .values_list('seccion', flat=True)
        .distinct()
    )
    for sec in secciones_usuarios:
        nombre_limpio = (sec or '').strip()[:60]
        if not nombre_limpio:
            continue
        existente = SeccionCurso.objects.filter(nombre__iexact=nombre_limpio).first()
        if not existente:
            SeccionCurso.objects.create(
                nombre=nombre_limpio,
                descripcion=descripciones_base.get(nombre_limpio.lower(), ''),
                activa=True,
            )
        elif existente.nombre != nombre_limpio:
            # Normalizar capitalización al nombre canónico registrado
            Usuario.objects.filter(seccion=sec).update(seccion=existente.nombre)


def revertir_secciones_existentes(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_seccioncurso'),
    ]

    operations = [
        migrations.RunPython(poblar_secciones_existentes, revertir_secciones_existentes),
    ]
