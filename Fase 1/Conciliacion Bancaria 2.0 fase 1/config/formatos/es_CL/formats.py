"""Formatos de número y fecha para Chile (es-CL).

Django no trae un formato propio para es-CL y usa el de español genérico, que separa
los miles con un espacio ("1 234 567"). En Chile se usa punto para miles y coma para
decimales: $ 1.234.567 y US$ 1.234,56.
"""

DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = "."
NUMBER_GROUPING = 3

DATE_FORMAT = r"j \d\e F \d\e Y"
SHORT_DATE_FORMAT = "d-m-Y"
DATETIME_FORMAT = r"j \d\e F \d\e Y, H:i"
SHORT_DATETIME_FORMAT = "d-m-Y H:i"
TIME_FORMAT = "H:i"
FIRST_DAY_OF_WEEK = 1  # lunes
DATE_INPUT_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"]
DATETIME_INPUT_FORMATS = ["%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
