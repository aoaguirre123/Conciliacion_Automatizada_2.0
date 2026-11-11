"""Parámetros de la conciliación que el administrador puede ajustar en «Configuración».

No depende de Django: los motores (logica.py y logica_clp.py) reciben un `Parametros` y, si no
se les entrega ninguno, usan los valores por defecto, que son los que la aplicación usaba fijos.
"""
import re
from dataclasses import dataclass, field

# Valores por defecto (los mismos que estaban fijos en el código).
TOLERANCIA_CLP = 10
TOLERANCIA_USD = 0.10
VENTANA_DIAS = 3
PALABRAS_CARTOLA = ("transbank", "tbk")

# Rangos aceptados en la pantalla de configuración.
RANGO_TOLERANCIA_CLP = (0, 1000)
RANGO_TOLERANCIA_USD = (0, 5)
RANGO_VENTANA_DIAS = (0, 15)


def separar_palabras(texto):
    """'Transbank, TBK ; abono comer' -> ('transbank', 'tbk', 'abono comer'), sin repetidas."""
    palabras = (p.strip().lower() for p in re.split(r"[,;\n]", texto or ""))
    return tuple(dict.fromkeys(p for p in palabras if p))


@dataclass(frozen=True)
class Parametros:
    tolerancia_clp: int = TOLERANCIA_CLP
    tolerancia_usd: float = TOLERANCIA_USD
    ventana_dias: int = VENTANA_DIAS
    palabras_cartola: tuple = field(default=PALABRAS_CARTOLA)

    def patron_cartola(self):
        """Expresión que reconoce en la glosa de la cartola un abono de Transbank."""
        palabras = self.palabras_cartola or PALABRAS_CARTOLA
        return re.compile("|".join(re.escape(p) for p in palabras), re.I)

    def como_dict(self):
        """Lo que se guarda con cada conciliación, para saber con qué criterios se hizo."""
        return {
            "tolerancia_clp": self.tolerancia_clp,
            "tolerancia_usd": self.tolerancia_usd,
            "ventana_dias": self.ventana_dias,
            "palabras_cartola": list(self.palabras_cartola),
        }
