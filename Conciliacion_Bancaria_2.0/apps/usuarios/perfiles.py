"""Perfiles de usuario y lo que puede hacer cada uno.

Cada perfil es un grupo de Django con el mismo nombre. Un usuario tiene un solo perfil:

    Administrador          concilia, consulta y además administra usuarios,
                           configuración y el borrado del historial.
    Analista de Tesorería  concilia en pesos y dólares, y consulta el historial.
    Contador / Auditor     solo consulta el historial, el detalle y los reportes.

Un superusuario siempre es Administrador. Una cuenta sin grupo (por ejemplo, creada
desde el admin de Django) se trata como antes de existir los perfiles: staff es
Administrador y el resto Analista de Tesorería.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.models import Group
from django.db import DatabaseError
from django.shortcuts import redirect

ADMINISTRADOR = "Administrador"
ANALISTA = "Analista de Tesorería"
CONSULTA = "Contador / Auditor"
SUPERUSUARIO = "Superusuario"  # etiqueta: tiene los permisos de Administrador y además gestiona administradores

ORDEN = (ADMINISTRADOR, ANALISTA, CONSULTA)

DESCRIPCION = {
    ADMINISTRADOR: "Concilia y consulta. Además administra usuarios, configuración y borrado del historial.",
    ANALISTA: "Carga archivos, concilia en pesos y dólares, y consulta el historial y los reportes.",
    CONSULTA: "Consulta el historial, el detalle y descarga los reportes. No concilia ni borra.",
}

ICONO = {
    ADMINISTRADOR: "shield-check",
    ANALISTA: "calculator",
    CONSULTA: "eye",
}

CLASE = {
    ADMINISTRADOR: "administrador",
    ANALISTA: "analista",
    CONSULTA: "consulta",
}

SOLO_ADMINISTRADORES = "Esa sección es solo para administradores."
SOLO_CONCILIADORES = (
    "Tu perfil permite consultar el historial y descargar reportes, pero no conciliar. "
    "Si lo necesitas, pide al administrador el perfil Analista de Tesorería."
)


def perfil_de(usuario):
    """Nombre del perfil del usuario, o None si no inició sesión."""
    if usuario is None or not usuario.is_authenticated:
        return None
    guardado = getattr(usuario, "_perfil", None)
    if guardado:
        return guardado
    if usuario.is_superuser:
        perfil = ADMINISTRADOR
    else:
        grupos = set(usuario.groups.values_list("name", flat=True))
        perfil = next((nombre for nombre in ORDEN if nombre in grupos), None)
        if perfil is None:
            perfil = ADMINISTRADOR if usuario.is_staff else ANALISTA
    usuario._perfil = perfil
    return perfil


def etiqueta_de(usuario):
    """Lo que se muestra en pantalla: «Superusuario» o el nombre del perfil."""
    if usuario is not None and usuario.is_authenticated and usuario.is_superuser:
        return SUPERUSUARIO
    return perfil_de(usuario)


def es_administrador(usuario):
    return perfil_de(usuario) == ADMINISTRADOR


def puede_conciliar(usuario):
    return perfil_de(usuario) in (ADMINISTRADOR, ANALISTA)


def asignar_perfil(usuario, perfil):
    """Deja al usuario (ya guardado) con un único perfil."""
    if perfil not in ORDEN:
        raise ValueError(f"Perfil desconocido: {perfil}")
    usuario.groups.remove(*Group.objects.filter(name__in=ORDEN))
    usuario.groups.add(Group.objects.get_or_create(name=perfil)[0])
    usuario._perfil = None
    usuario._perfil = perfil_de(usuario)


def datos_plantilla(usuario):
    """Variables para todas las plantillas (ver apps.core.context_processors)."""
    try:
        perfil = perfil_de(usuario)
    except DatabaseError:
        perfil = None
    return {
        "perfil": perfil,
        "etiqueta_perfil": SUPERUSUARIO if perfil and usuario.is_superuser else perfil,
        "es_admin": perfil == ADMINISTRADOR,
        "puede_conciliar": perfil in (ADMINISTRADOR, ANALISTA),
    }


def _exigir(prueba, mensaje, destino):
    def decorador(vista):
        @wraps(vista)
        def envuelta(request, *args, **kwargs):
            if not prueba(request.user):
                messages.error(request, mensaje)
                return redirect(destino)
            return vista(request, *args, **kwargs)
        return envuelta
    return decorador


def solo_administradores(vista=None, *, mensaje=SOLO_ADMINISTRADORES, destino="core:inicio"):
    """Va debajo de @login_required. Sin permiso, vuelve a `destino` con un mensaje."""
    decorador = _exigir(es_administrador, mensaje, destino)
    return decorador(vista) if vista else decorador


def solo_conciliadores(vista=None, *, destino="core:inicio"):
    """Administrador o Analista. Va debajo de @login_required."""
    decorador = _exigir(puede_conciliar, SOLO_CONCILIADORES, destino)
    return decorador(vista) if vista else decorador
