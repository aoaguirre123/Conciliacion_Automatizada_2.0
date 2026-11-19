"""Acciones sugeridas más cortas: se rehacen las de las excepciones ya guardadas."""
from django.db import migrations


def rehacer_sugerencias(apps, schema_editor):
    from apps.conciliacion import excepciones

    Conciliacion = apps.get_model("conciliacion", "Conciliacion")
    Excepcion = apps.get_model("conciliacion", "Excepcion")

    for c in Conciliacion.objects.filter(excepciones__isnull=False).distinct().iterator():
        r = c.resultado or {}
        # En pesos se puede volver a armar cada caso completo (con el código del BORDERO y la cuota).
        casos = excepciones.desde_clp(r.get("observaciones"), r.get("cuotas")) if c.moneda == "CLP" else []
        cambiadas = []
        for e in Excepcion.objects.filter(conciliacion=c):
            caso = casos[e.orden] if e.orden < len(casos) and casos[e.orden]["categoria"] == e.categoria_auto else None
            if caso and e.categoria == e.categoria_auto:
                e.sugerencia = caso["sugerencia"]
            else:
                datos = {
                    "moneda": c.moneda, "nota": e.detalle, "medio": e.medio, "codigo": e.codigo,
                    "fecha": e.fecha.strftime("%d-%m-%Y") if e.fecha else "",
                    "diferencia": float(e.diferencia) if e.diferencia is not None else None,
                }
                e.sugerencia = excepciones.sugerencia_de(e.categoria, datos)
            cambiadas.append(e)
        Excepcion.objects.bulk_update(cambiadas, ["sugerencia"])


class Migration(migrations.Migration):
    dependencies = [("conciliacion", "0006_excepciones")]
    operations = [migrations.RunPython(rehacer_sugerencias, migrations.RunPython.noop)]
