from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.shortcuts import redirect, render


def login(request):
    if request.user.is_authenticated:
        return redirect("home")

    contexto = {}
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        user_record = User.objects.filter(email__iexact=email).first()
        username = user_record.username if user_record else None
        user = authenticate(request, username=username, password=password)

        if user is not None and user.is_active:
            auth_login(request, user)
            return redirect("home")

        contexto["mensaje"] = "Correo o contraseña incorrectos."

    return render(request, "auth/login.html", contexto)


def cerrar_sesion(request):
    auth_logout(request)
    return redirect("home")