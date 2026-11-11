from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from . import parametros as p


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


class Configuracion(models.Model):
    """Parámetros de la conciliación que ajusta el administrador. Hay una sola fila (pk=1)."""

    tolerancia_clp = models.PositiveIntegerField(
        "tolerancia en pesos", default=p.TOLERANCIA_CLP,
        validators=[MinValueValidator(p.RANGO_TOLERANCIA_CLP[0]), MaxValueValidator(p.RANGO_TOLERANCIA_CLP[1])],
        help_text="Diferencia máxima, en pesos, entre Transbank y el BORDERO para dar una venta por conciliada.",
    )
    tolerancia_usd = models.DecimalField(
        "tolerancia en dólares", max_digits=4, decimal_places=2, default=Decimal(str(p.TOLERANCIA_USD)),
        validators=[MinValueValidator(Decimal(p.RANGO_TOLERANCIA_USD[0])), MaxValueValidator(Decimal(p.RANGO_TOLERANCIA_USD[1]))],
        help_text="Diferencia máxima, en dólares, que se considera redondeo.",
    )
    ventana_dias = models.PositiveSmallIntegerField(
        "ventana de días", default=p.VENTANA_DIAS,
        validators=[MinValueValidator(p.RANGO_VENTANA_DIAS[0]), MaxValueValidator(p.RANGO_VENTANA_DIAS[1])],
        help_text="Días de diferencia aceptados entre la venta y el pago registrado.",
    )
    palabras_cartola = models.CharField(
        "palabras clave de la cartola", max_length=300, default=", ".join(p.PALABRAS_CARTOLA),
        help_text="Palabras que identifican en la glosa de la cartola un abono de Transbank, separadas por comas.",
    )
    actualizada = models.DateTimeField(auto_now=True)
    actualizada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="+")

    class Meta:
        verbose_name = "configuración"
        verbose_name_plural = "configuración"

    def __str__(self):
        return "Configuración de la conciliación"

    def save(self, *args, **kwargs):
        self.pk = 1  # una sola configuración
        super().save(*args, **kwargs)

    @classmethod
    def actual(cls):
        """La configuración guardada o, si aún no se guarda ninguna, los valores por defecto (sin escribir)."""
        return cls.objects.filter(pk=1).first() or cls(pk=1)

    def es_por_defecto(self):
        return self.parametros() == p.Parametros()

    def restablecer(self):
        """Vuelve todos los valores a los por defecto (sin guardar)."""
        for campo in ("tolerancia_clp", "tolerancia_usd", "ventana_dias", "palabras_cartola"):
            setattr(self, campo, self._meta.get_field(campo).get_default())

    def parametros(self):
        return p.Parametros(
            tolerancia_clp=int(self.tolerancia_clp),
            tolerancia_usd=float(self.tolerancia_usd),
            ventana_dias=int(self.ventana_dias),
            palabras_cartola=p.separar_palabras(self.palabras_cartola) or p.PALABRAS_CARTOLA,
        )
