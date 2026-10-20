from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


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


@require_POST
def cerrar_sesion(request):
    logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
