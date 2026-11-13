from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from . import perfiles as p

AYUDA_CLAVE = "Mínimo 8 caracteres. No puede ser solo números, muy común ni parecida al nombre o correo."


def _entrada(**extra):
    return {"class": "entrada", **extra}


def _otros_administradores_activos(excluir):
    """¿Queda otro administrador activo si `excluir` deja de serlo?"""
    return any(
        p.es_administrador(u)
        for u in User.objects.filter(is_active=True).exclude(pk=excluir.pk).prefetch_related("groups")
    )


class UsuarioForm(forms.ModelForm):
    """Datos y perfil. Lo usan las pantallas de nuevo usuario y de edición."""

    perfil = forms.ChoiceField(
        label="Perfil",
        choices=[(nombre, nombre) for nombre in p.ORDEN],
        widget=forms.RadioSelect,
        error_messages={"required": "Elige un perfil.", "invalid_choice": "Elige uno de los perfiles de la lista."},
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "is_active"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Correo electrónico",
            "is_active": "Cuenta activa",
        }
        widgets = {
            "first_name": forms.TextInput(attrs=_entrada(autocomplete="off")),
            "last_name": forms.TextInput(attrs=_entrada(autocomplete="off")),
            "email": forms.EmailInput(attrs=_entrada(autocomplete="off")),
        }
        error_messages = {
            "email": {"invalid": "Escribe un correo válido, por ejemplo nombre@hotel.cl."},
        }

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        # Los administradores solo los crea, cambia o desactiva un superusuario.
        self.maneja_administradores = editor is None or editor.is_superuser
        self.administrador_protegido = False
        for nombre in ("first_name", "last_name", "email"):
            self.fields[nombre].required = True
        self.fields["first_name"].error_messages["required"] = "Escribe el nombre."
        self.fields["last_name"].error_messages["required"] = "Escribe el apellido."
        self.fields["email"].error_messages["required"] = "Escribe el correo con que iniciará sesión."
        if self.instance.pk:
            self.initial.setdefault("perfil", p.perfil_de(self.instance))
            if self.instance.is_superuser:
                # El superusuario siempre es administrador; se muestra pero no se cambia.
                self.fields["perfil"].disabled = True
            elif not self.maneja_administradores and p.es_administrador(self.instance):
                self.administrador_protegido = True
                self.fields["perfil"].disabled = True
                self.fields["is_active"].disabled = True
        else:
            del self.fields["is_active"]
            self.initial.setdefault("perfil", p.ANALISTA)
        if not self.maneja_administradores and not self.fields["perfil"].disabled:
            self.fields["perfil"].choices = [(n, n) for n in p.ORDEN if n != p.ADMINISTRADOR]

    @property
    def es_uno_mismo(self):
        return self.editor is not None and self.instance.pk == self.editor.pk

    def clean_email(self):
        correo = self.cleaned_data["email"].strip().lower()
        repetido = User.objects.filter(email__iexact=correo).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe una cuenta con ese correo.")
        return correo

    def clean(self):
        datos = super().clean()
        if not self.instance.pk:
            return datos
        era_admin = p.es_administrador(self.instance)
        sigue_admin = self.instance.is_superuser or datos.get("perfil") == p.ADMINISTRADOR
        sigue_activo = datos.get("is_active", self.instance.is_active)
        if self.es_uno_mismo:
            if era_admin and not sigue_admin:
                self.add_error("perfil", "No puedes quitarte el perfil de administrador a ti mismo.")
            if not sigue_activo:
                self.add_error("is_active", "No puedes desactivar tu propia cuenta.")
        elif era_admin and self.instance.is_active and (not sigue_admin or not sigue_activo):
            if not _otros_administradores_activos(self.instance):
                self.add_error(None, "Debe quedar al menos un administrador activo.")
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if not usuario.pk:
            usuario.username = self.cleaned_data["email"][:150]
        if commit:
            usuario.save()
            if not usuario.is_superuser:
                p.asignar_perfil(usuario, self.cleaned_data["perfil"])
                usuario.is_staff = self.cleaned_data["perfil"] == p.ADMINISTRADOR
                usuario.save(update_fields=["is_staff"])
        return usuario


class ClaveForm(forms.Form):
    """Contraseña nueva, escrita dos veces y revisada con los validadores de Django."""

    clave = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs=_entrada(autocomplete="new-password")),
        error_messages={"required": "Escribe una contraseña."},
    )
    clave_repetida = forms.CharField(
        label="Repite la contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs=_entrada(autocomplete="new-password")),
        error_messages={"required": "Repite la contraseña."},
    )

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario

    def clean(self):
        datos = super().clean()
        clave, repetida = datos.get("clave"), datos.get("clave_repetida")
        if clave and repetida and clave != repetida:
            self.add_error("clave_repetida", "Las contraseñas no coinciden.")
        elif clave:
            try:
                validate_password(clave, self.usuario)
            except forms.ValidationError as error:
                self.add_error("clave", error)
        return datos


class NuevoUsuarioForm(UsuarioForm):
    """Datos, perfil y contraseña inicial."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.update(ClaveForm().fields)

    def clean(self):
        datos = super().clean()
        clave, repetida = datos.get("clave"), datos.get("clave_repetida")
        if clave and repetida and clave != repetida:
            self.add_error("clave_repetida", "Las contraseñas no coinciden.")
        elif clave:
            provisorio = User(
                username=datos.get("email") or "",
                email=datos.get("email") or "",
                first_name=datos.get("first_name") or "",
                last_name=datos.get("last_name") or "",
            )
            try:
                validate_password(clave, provisorio)
            except forms.ValidationError as error:
                self.add_error("clave", error)
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["clave"])
        if commit:
            usuario.save()
            p.asignar_perfil(usuario, self.cleaned_data["perfil"])
            usuario.is_staff = self.cleaned_data["perfil"] == p.ADMINISTRADOR
            usuario.save(update_fields=["is_staff"])
        return usuario
