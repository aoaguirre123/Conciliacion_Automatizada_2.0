from django import forms

from . import parametros as p
from .models import Configuracion


class ConfiguracionForm(forms.ModelForm):
    class Meta:
        model = Configuracion
        fields = ["tolerancia_clp", "tolerancia_usd", "ventana_dias", "palabras_cartola"]
        widgets = {
            "tolerancia_clp": forms.NumberInput(attrs={"class": "entrada", "min": p.RANGO_TOLERANCIA_CLP[0],
                                                       "max": p.RANGO_TOLERANCIA_CLP[1], "step": 1}),
            "tolerancia_usd": forms.NumberInput(attrs={"class": "entrada", "min": p.RANGO_TOLERANCIA_USD[0],
                                                       "max": p.RANGO_TOLERANCIA_USD[1], "step": "0.01"}),
            "ventana_dias": forms.NumberInput(attrs={"class": "entrada", "min": p.RANGO_VENTANA_DIAS[0],
                                                     "max": p.RANGO_VENTANA_DIAS[1], "step": 1}),
            "palabras_cartola": forms.TextInput(attrs={"class": "entrada"}),
        }
        error_messages = {
            "tolerancia_clp": {
                "min_value": "La tolerancia en pesos no puede ser negativa.",
                "max_value": f"La tolerancia en pesos no puede superar ${p.RANGO_TOLERANCIA_CLP[1]:,}.".replace(",", "."),
            },
            "tolerancia_usd": {
                "min_value": "La tolerancia en dólares no puede ser negativa.",
                "max_value": f"La tolerancia en dólares no puede superar US$ {p.RANGO_TOLERANCIA_USD[1]}.",
            },
            "ventana_dias": {
                "min_value": "La ventana de días no puede ser negativa.",
                "max_value": f"La ventana de días no puede superar {p.RANGO_VENTANA_DIAS[1]} días.",
            },
        }

    def clean_palabras_cartola(self):
        palabras = p.separar_palabras(self.cleaned_data["palabras_cartola"])
        if not palabras:
            raise forms.ValidationError("Ingresa al menos una palabra clave, por ejemplo «transbank».")
        cortas = [x for x in palabras if len(x) < 3]
        if cortas:
            raise forms.ValidationError(
                "Cada palabra clave debe tener al menos 3 letras para no confundir otros movimientos: "
                + ", ".join(cortas) + "."
            )
        return ", ".join(palabras)
