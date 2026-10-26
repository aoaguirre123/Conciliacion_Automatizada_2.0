import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Conciliacion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("moneda", models.CharField(choices=[("USD", "Dólares"), ("CLP", "Pesos")], max_length=3)),
                ("creada", models.DateTimeField(auto_now_add=True)),
                ("archivos", models.JSONField(default=list, help_text="Nombre y tamaño de cada archivo analizado.")),
                ("cuadrado", models.BooleanField(default=False)),
                ("monto_por_revisar", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("resultado", models.JSONField(default=dict, help_text="Datos que se muestran en pantalla.")),
                ("usuario", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="conciliaciones", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "conciliación",
                "verbose_name_plural": "conciliaciones",
                "ordering": ["-creada"],
            },
        ),
        migrations.CreateModel(
            name="Reporte",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("clave", models.SlugField(max_length=40)),
                ("titulo", models.CharField(max_length=120)),
                ("descripcion", models.CharField(blank=True, max_length=200)),
                ("nombre_archivo", models.CharField(max_length=150)),
                ("contenido", models.BinaryField()),
                ("orden", models.PositiveSmallIntegerField(default=0)),
                ("conciliacion", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reportes", to="conciliacion.conciliacion")),
            ],
            options={
                "ordering": ["orden"],
                "constraints": [models.UniqueConstraint(fields=("conciliacion", "clave"), name="reporte_unico_por_conciliacion")],
            },
        ),
    ]
