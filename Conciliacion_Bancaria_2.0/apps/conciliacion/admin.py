from django.contrib import admin

from .models import BinTarjeta, Conciliacion, Reporte


class ReporteEnLinea(admin.TabularInline):
    model = Reporte
    fields = ("titulo", "nombre_archivo")
    readonly_fields = fields
    extra = 0
    can_delete = False


@admin.register(Conciliacion)
class ConciliacionAdmin(admin.ModelAdmin):
    list_display = ("id", "moneda", "creada", "desde", "hasta", "usuario", "cuadrado", "monto_por_revisar")
    list_filter = ("moneda", "cuadrado")
    readonly_fields = ("moneda", "creada", "desde", "hasta", "usuario", "archivos", "cuadrado", "monto_por_revisar", "resultado")
    inlines = [ReporteEnLinea]


@admin.register(BinTarjeta)
class BinTarjetaAdmin(admin.ModelAdmin):
    list_display = ("bin", "marca", "tipo", "nivel", "banco", "pais")
    list_filter = ("marca", "tipo", "pais_codigo")
    search_fields = ("bin", "banco")
    show_full_result_count = False  # son ~375.000 filas: evita contar todo en cada búsqueda
