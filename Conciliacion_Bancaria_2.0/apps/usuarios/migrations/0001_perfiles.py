"""Crea los tres perfiles (grupos) y asigna uno a cada cuenta existente.

Las cuentas que ya existían conservan lo que podían hacer: superusuarios y staff
quedan como Administrador, el resto como Analista de Tesorería.
"""
from django.db import migrations

ADMINISTRADOR = "Administrador"
ANALISTA = "Analista de Tesorería"
CONSULTA = "Contador / Auditor"
PERFILES = (ADMINISTRADOR, ANALISTA, CONSULTA)


def crear_perfiles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    grupos = {nombre: Group.objects.get_or_create(name=nombre)[0] for nombre in PERFILES}
    for usuario in User.objects.all():
        if usuario.groups.filter(name__in=PERFILES).exists():
            continue
        perfil = ADMINISTRADOR if (usuario.is_superuser or usuario.is_staff) else ANALISTA
        usuario.groups.add(grupos[perfil])


def quitar_perfiles(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=PERFILES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(crear_perfiles, quitar_perfiles),
    ]
