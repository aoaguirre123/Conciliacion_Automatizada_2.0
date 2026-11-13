from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

from . import perfiles as p
from .forms import ClaveForm, NuevoUsuarioForm, UsuarioForm


def _destino(request):
    """Página a la que volver tras ingresar (?next=...), solo si es de este sitio."""
    destino = request.POST.get("next") or request.GET.get("next")
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return resolve_url(settings.LOGIN_REDIRECT_URL)


def iniciar_sesion(request):
    if request.user.is_authenticated:
        return redirect(_destino(request))

    contexto = {"next": request.GET.get("next", "")}
    if contexto["next"] and request.method == "GET":
        contexto["aviso"] = "Inicia sesión para continuar. Si estabas trabajando, tu sesión terminó."
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        registro = User.objects.filter(email__iexact=email).first()
        usuario = authenticate(request, username=registro.username if registro else None, password=password)

        if usuario is not None and usuario.is_active:
            login(request, usuario)
            if not request.POST.get("recordarme"):
                request.session.set_expiry(0)  # termina al cerrar el navegador
            return redirect(_destino(request))

        contexto.update(
            mensaje="Correo o contraseña incorrectos.",
            email=email,
            next=request.POST.get("next", ""),
        )

    return render(request, "usuarios/login.html", contexto)


def cerrar_sesion(request):
    if request.method != "POST":  # abrir /usuarios/logout/ en el navegador no cierra la sesión
        return redirect(settings.LOGIN_REDIRECT_URL if request.user.is_authenticated else settings.LOGIN_URL)
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)


# ---------------------------------------------------------------------------
# Administración de usuarios (solo administradores)
# ---------------------------------------------------------------------------
def _nombre(usuario):
    return usuario.get_full_name() or usuario.email or usuario.username


@login_required
@p.solo_administradores
def lista(request):
    usuarios = list(User.objects.prefetch_related("groups").order_by("-is_active", "first_name", "last_name", "username"))
    for u in usuarios:
        u.perfil = p.perfil_de(u)
        u.etiqueta = p.etiqueta_de(u)
        u.perfil_clase = "superusuario" if u.is_superuser else p.CLASE[u.perfil]
    resumen = [
        {
            "nombre": nombre,
            "descripcion": p.DESCRIPCION[nombre],
            "icono": p.ICONO[nombre],
            "clase": p.CLASE[nombre],
            "total": sum(1 for u in usuarios if u.perfil == nombre and u.is_active and not u.is_superuser),
        }
        for nombre in p.ORDEN
    ]
    return render(request, "usuarios/lista.html", {
        "usuarios": usuarios,
        "resumen": resumen,
        "inactivos": sum(1 for u in usuarios if not u.is_active),
    })


def _opciones_perfil(formulario):
    """Las opciones del campo perfil con su descripción, para dibujarlas como tarjetas."""
    return [
        {
            "opcion": opcion,
            "descripcion": p.DESCRIPCION[opcion.data["value"]],
            "icono": p.ICONO[opcion.data["value"]],
        }
        for opcion in formulario["perfil"]
    ]


@login_required
@p.solo_administradores
def nuevo(request):
    formulario = NuevoUsuarioForm(request.POST or None, editor=request.user)
    if request.method == "POST" and formulario.is_valid():
        usuario = formulario.save()
        messages.success(
            request,
            f"Se creó la cuenta de {_nombre(usuario)} con el perfil {p.perfil_de(usuario)}. "
            "Ya puede iniciar sesión con su correo y la contraseña que le definiste.",
        )
        return redirect("usuarios:lista")
    return render(request, "usuarios/formulario.html", {
        "formulario": formulario,
        "opciones_perfil": _opciones_perfil(formulario),
        "nuevo": True,
    })


@login_required
@p.solo_administradores
def editar(request, pk):
    usuario = User.objects.filter(pk=pk).first()
    if usuario is None:
        messages.warning(request, "Ese usuario no existe.")
        return redirect("usuarios:lista")

    accion = request.POST.get("accion") if request.method == "POST" else None
    formulario = UsuarioForm(request.POST if accion == "datos" else None, instance=usuario, editor=request.user)
    # La contraseña de otro administrador solo la cambia un superusuario.
    puede_cambiar_clave = usuario.pk == request.user.pk or not formulario.administrador_protegido
    clave = ClaveForm(request.POST if accion == "clave" else None, usuario=usuario) if puede_cambiar_clave else None

    if accion == "clave" and clave is None:
        messages.error(request, "Solo el superusuario puede cambiar la contraseña de otro administrador.")
        return redirect("usuarios:editar", pk=usuario.pk)

    if accion == "datos" and formulario.is_valid():
        formulario.save()
        messages.success(request, f"Se guardaron los cambios de {_nombre(usuario)}.")
        return redirect("usuarios:lista")
    if accion == "clave" and clave.is_valid():
        usuario.set_password(clave.cleaned_data["clave"])
        usuario.save(update_fields=["password"])
        if usuario.pk == request.user.pk:
            update_session_auth_hash(request, usuario)  # no cerrar la propia sesión
        messages.success(request, f"Se cambió la contraseña de {_nombre(usuario)}.")
        return redirect("usuarios:editar", pk=usuario.pk)

    return render(request, "usuarios/formulario.html", {
        "formulario": formulario,
        "clave": clave,
        "opciones_perfil": _opciones_perfil(formulario),
        "editado": usuario,
        "uno_mismo": usuario.pk == request.user.pk,
    })
