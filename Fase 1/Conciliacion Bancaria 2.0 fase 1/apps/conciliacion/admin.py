from django.contrib import admin

from .models import Conciliacion, Reporte


class ReporteEnLinea(admin.TabularInline):
    model = Reporte
    fields = ("titulo", "nombre_archivo")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(Conciliacion)
class ConciliacionAdmin(admin.ModelAdmin):
    list_display = ("id", "moneda", "creada", "usuario", "cuadrado", "monto_por_revisar")
    list_filter = ("moneda", "cuadrado")
    readonly_fields = ("moneda", "creada", "usuario", "archivos", "cuadrado", "monto_por_revisar", "resultado")
    inlines = [ReporteEnLinea]
