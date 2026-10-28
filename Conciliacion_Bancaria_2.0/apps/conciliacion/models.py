from django.conf import settings
from django.db import models
from django.urls import reverse


class Conciliacion(models.Model):
    """Una conciliación ejecutada. Guarda lo necesario para volver a verla sin reprocesar."""

    DOLARES = "USD"
    PESOS = "CLP"
    MONEDAS = [(DOLARES, "Dólares"), (PESOS, "Pesos")]

    moneda = models.CharField(max_length=3, choices=MONEDAS)
    creada = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="conciliaciones")
    archivos = models.JSONField(default=list, help_text="Nombre y tamaño de cada archivo analizado.")
    cuadrado = models.BooleanField(default=False)
    monto_por_revisar = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    desde = models.DateField(null=True, blank=True, help_text="Primer día del período conciliado.")
    hasta = models.DateField(null=True, blank=True, help_text="Fecha de corte: último día del período conciliado.")
    resultado = models.JSONField(default=dict, help_text="Datos que se muestran en pantalla.")

    class Meta:
        ordering = ["-creada"]
        verbose_name = "conciliación"
        verbose_name_plural = "conciliaciones"

    def __str__(self):
        return f"Conciliación en {self.get_moneda_display().lower()} #{self.pk}"

    def get_absolute_url(self):
        return reverse("conciliacion:detalle", args=[self.pk])

    @property
    def simbolo(self):
        return "US$" if self.moneda == self.DOLARES else "$"


class Reporte(models.Model):
    """Excel generado por una conciliación, listo para descargar."""

    conciliacion = models.ForeignKey(Conciliacion, on_delete=models.CASCADE, related_name="reportes")
    clave = models.SlugField(max_length=40)
    titulo = models.CharField(max_length=120)
    descripcion = models.CharField(max_length=200, blank=True)
    nombre_archivo = models.CharField(max_length=150)
    contenido = models.BinaryField()
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden"]
        constraints = [models.UniqueConstraint(fields=["conciliacion", "clave"], name="reporte_unico_por_conciliacion")]

    def __str__(self):
        return self.nombre_archivo

    def get_absolute_url(self):
        return reverse("conciliacion:descargar", args=[self.conciliacion_id, self.clave])


class BinTarjeta(models.Model):
    """Datos de un BIN (6 primeros dígitos de la tarjeta). Se carga con migrate desde datos/bines.csv.gz."""

    bin = models.CharField(max_length=6, primary_key=True)
    marca = models.CharField(max_length=30)
    tipo = models.CharField(max_length=10, blank=True, help_text="Crédito, Débito o Prepago.")
    nivel = models.CharField(max_length=40, blank=True, help_text="Classic, Gold, Platinum…")
    banco = models.CharField(max_length=120, blank=True)
    pais_codigo = models.CharField(max_length=2, blank=True)
    pais = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["bin"]
        verbose_name = "BIN de tarjeta"
        verbose_name_plural = "BIN de tarjetas"

    def __str__(self):
        return f"{self.bin} {self.marca} {self.banco}".strip()
