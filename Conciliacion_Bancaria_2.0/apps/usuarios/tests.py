from django.contrib.auth.models import Group, User
from django.test import TestCase

from apps.conciliacion.models import Conciliacion

from . import perfiles as p

CLAVE = "Clave-Prueba-2026"


def crear(username, perfil=None, **extra):
    usuario = User.objects.create_user(username, f"{username}@hotel.cl", CLAVE, **extra)
    if perfil:
        p.asignar_perfil(usuario, perfil)
    return usuario


class PerfilesTests(TestCase):
    def test_la_migracion_crea_los_tres_perfiles(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(p.ORDEN))

    def test_perfil_segun_grupo_superusuario_y_cuentas_antiguas(self):
        self.assertEqual(p.perfil_de(crear("ana", p.CONSULTA)), p.CONSULTA)
        self.assertEqual(p.perfil_de(crear("raiz", is_superuser=True)), p.ADMINISTRADOR)
        self.assertEqual(p.perfil_de(crear("jefe", is_staff=True)), p.ADMINISTRADOR)
        self.assertEqual(p.perfil_de(crear("sin_grupo")), p.ANALISTA)

    def test_asignar_reemplaza_el_perfil_anterior(self):
        usuario = crear("ana", p.ADMINISTRADOR)
        p.asignar_perfil(usuario, p.CONSULTA)
        usuario = User.objects.get(pk=usuario.pk)
        self.assertEqual(list(usuario.groups.values_list("name", flat=True)), [p.CONSULTA])


class PermisosTests(TestCase):
    def setUp(self):
        self.conciliacion = Conciliacion.objects.create(moneda=Conciliacion.PESOS)

    def entrar(self, perfil):
        self.client.force_login(crear(perfil.split()[0].lower(), perfil))

    def test_contador_consulta_pero_no_concilia(self):
        self.entrar(p.CONSULTA)
        for url in ("/conciliacion/", "/conciliacion/pesos/"):
            respuesta = self.client.get(url, follow=True)
            self.assertRedirects(respuesta, "/")
            self.assertContains(respuesta, "no conciliar")
        respuesta = self.client.post("/conciliacion/pesos/ejemplo/")
        self.assertRedirects(respuesta, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/conciliacion/historial/").status_code, 200)
        self.assertEqual(self.client.get(f"/conciliacion/historial/{self.conciliacion.pk}/").status_code, 200)
        inicio = self.client.get("/")
        self.assertContains(inicio, "Tu perfil es de consulta")
        self.assertNotContains(inicio, 'href="/conciliacion/pesos/"')

    def test_analista_concilia_pero_no_borra_ni_administra(self):
        self.entrar(p.ANALISTA)
        self.assertEqual(self.client.get("/conciliacion/pesos/").status_code, 200)
        historial = self.client.get("/conciliacion/historial/")
        self.assertNotContains(historial, "Borrar seleccionadas")
        self.assertNotContains(historial, 'name="ids"')
        respuesta = self.client.post("/conciliacion/historial/borrar/confirmar/",
                                     {"ids": str(self.conciliacion.pk), "entiendo": "1"}, follow=True)
        self.assertContains(respuesta, "Solo un administrador puede borrar")
        self.assertTrue(Conciliacion.objects.filter(pk=self.conciliacion.pk).exists())
        for url in ("/usuarios/", "/usuarios/nuevo/", "/conciliacion/configuracion/"):
            self.assertRedirects(self.client.get(url), "/", fetch_redirect_response=False)
        self.assertNotContains(self.client.get("/"), 'href="/usuarios/"')

    def test_solo_el_administrador_concilia_con_archivos_de_ejemplo(self):
        for perfil, moneda in ((p.ANALISTA, "pesos"), (p.CONSULTA, "pesos")):
            self.client.force_login(crear(perfil.split()[0].lower() + moneda, perfil))
            url = "/conciliacion/pesos/ejemplo/"
            respuesta = self.client.post(url, follow=True)
            self.assertNotEqual(Conciliacion.objects.count(), 2)
            if perfil == p.ANALISTA:
                self.assertContains(respuesta, "Solo un administrador puede conciliar con los archivos de ejemplo.")
                self.assertNotContains(self.client.get("/conciliacion/pesos/"), "Conciliar con archivos de ejemplo")
                self.assertNotContains(self.client.get("/conciliacion/"), "Conciliar con archivos de ejemplo")
        self.entrar(p.ADMINISTRADOR)
        self.assertContains(self.client.get("/conciliacion/pesos/"), "Conciliar con archivos de ejemplo")
        self.assertContains(self.client.get("/conciliacion/"), "Conciliar con archivos de ejemplo")

    def test_administrador_ve_usuarios_en_el_menu_y_no_el_admin_de_django(self):
        self.entrar(p.ADMINISTRADOR)
        inicio = self.client.get("/")
        self.assertContains(inicio, 'href="/usuarios/"')
        self.assertNotContains(inicio, 'href="/admin/"')
        self.assertContains(self.client.get("/conciliacion/historial/"), "Borrar seleccionadas")

    def test_la_cabecera_muestra_el_perfil(self):
        self.entrar(p.ANALISTA)
        self.assertContains(self.client.get("/"), "Analista de Tesorería")


class AdministrarUsuariosTests(TestCase):
    def setUp(self):
        self.admin = crear("jefa", p.ADMINISTRADOR, first_name="Ana", last_name="Rojas")
        self.client.force_login(self.admin)

    def datos(self, **cambios):
        datos = {
            "accion": "datos", "first_name": "Pedro", "last_name": "Soto", "email": "Pedro.Soto@Hotel.cl",
            "perfil": p.CONSULTA, "clave": "Conciliar-2026", "clave_repetida": "Conciliar-2026",
        }
        datos.update(cambios)
        return datos

    def test_lista_muestra_perfiles_y_cuentas(self):
        crear("pedro", p.CONSULTA, first_name="Pedro", is_active=False)
        pagina = self.client.get("/usuarios/")
        self.assertContains(pagina, "Nuevo usuario")
        self.assertContains(pagina, "Contador / Auditor")
        self.assertContains(pagina, "Desactivada")
        self.assertContains(pagina, "Tú")

    def test_crear_usuario_con_perfil(self):
        respuesta = self.client.post("/usuarios/nuevo/", self.datos(), follow=True)
        self.assertRedirects(respuesta, "/usuarios/")
        self.assertContains(respuesta, "Se creó la cuenta de Pedro Soto con el perfil Contador / Auditor")
        nuevo = User.objects.get(email="pedro.soto@hotel.cl")
        self.assertEqual(nuevo.username, "pedro.soto@hotel.cl")
        self.assertEqual(p.perfil_de(nuevo), p.CONSULTA)
        self.assertFalse(nuevo.is_staff)
        self.assertTrue(nuevo.check_password("Conciliar-2026"))
        # Puede iniciar sesión con su correo.
        self.client.logout()
        respuesta = self.client.post("/usuarios/login/", {"email": "pedro.soto@hotel.cl", "password": "Conciliar-2026"})
        self.assertRedirects(respuesta, "/", fetch_redirect_response=False)

    def test_un_administrador_no_puede_crear_administradores(self):
        pagina = self.client.get("/usuarios/nuevo/")
        self.assertNotContains(pagina, 'value="Administrador"')
        self.assertContains(pagina, "El perfil Administrador solo lo asigna el superusuario.")
        respuesta = self.client.post("/usuarios/nuevo/", self.datos(perfil=p.ADMINISTRADOR))
        self.assertContains(respuesta, "Elige uno de los perfiles de la lista.")
        self.assertFalse(User.objects.filter(email="pedro.soto@hotel.cl").exists())

    def test_el_superusuario_crea_administradores(self):
        self.client.force_login(crear("raiz", is_superuser=True))
        self.assertContains(self.client.get("/usuarios/nuevo/"), 'value="Administrador"')
        self.client.post("/usuarios/nuevo/", self.datos(perfil=p.ADMINISTRADOR))
        nuevo = User.objects.get(email="pedro.soto@hotel.cl")
        self.assertEqual(p.perfil_de(nuevo), p.ADMINISTRADOR)
        self.assertTrue(nuevo.is_staff)

    def test_un_administrador_no_modifica_a_otro_administrador(self):
        otra = crear("otra", p.ADMINISTRADOR)
        pagina = self.client.get(f"/usuarios/{otra.pk}/")
        self.assertContains(pagina, "Solo el superusuario puede cambiar el perfil de un administrador, desactivarlo o cambiar su contraseña.")
        self.assertNotContains(pagina, 'id="form-clave"')
        # Aunque se envíe a mano, el perfil y el estado no cambian.
        self.client.post(f"/usuarios/{otra.pk}/", {
            "accion": "datos", "first_name": "Otra", "last_name": "Admin", "email": "otra@hotel.cl", "perfil": p.CONSULTA,
        })
        otra = User.objects.get(pk=otra.pk)
        self.assertEqual(p.perfil_de(otra), p.ADMINISTRADOR)
        self.assertTrue(otra.is_active)
        respuesta = self.client.post(f"/usuarios/{otra.pk}/", {
            "accion": "clave", "clave": "Nueva-Clave-2026", "clave_repetida": "Nueva-Clave-2026",
        }, follow=True)
        self.assertContains(respuesta, "Solo el superusuario puede cambiar la contraseña de otro administrador.")
        self.assertTrue(User.objects.get(pk=otra.pk).check_password(CLAVE))

    def test_el_superusuario_modifica_administradores(self):
        otra = crear("otra", p.ADMINISTRADOR)
        self.client.force_login(crear("raiz", is_superuser=True))
        self.client.post(f"/usuarios/{otra.pk}/", {
            "accion": "datos", "first_name": "Otra", "last_name": "Admin", "email": "otra@hotel.cl", "perfil": p.CONSULTA,
        })
        otra = User.objects.get(pk=otra.pk)
        self.assertEqual(p.perfil_de(otra), p.CONSULTA)
        self.assertFalse(otra.is_active)
        self.assertFalse(otra.is_staff)

    def test_validaciones_al_crear(self):
        User.objects.create_user("pedro", "pedro.soto@hotel.cl", CLAVE)
        casos = [
            (self.datos(email="PEDRO.SOTO@hotel.cl"), "Ya existe una cuenta con ese correo."),
            (self.datos(email="otro@hotel.cl", clave_repetida="Otra-2026"), "Las contraseñas no coinciden."),
            (self.datos(email="otro@hotel.cl", clave="12345678", clave_repetida="12345678"), "completamente numérica"),
            (self.datos(email="otro@hotel.cl", perfil=""), "Elige un perfil."),
            (self.datos(email="otro@hotel.cl", first_name=""), "Escribe el nombre."),
        ]
        for datos, mensaje in casos:
            with self.subTest(mensaje=mensaje):
                respuesta = self.client.post("/usuarios/nuevo/", datos)
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, "No se creó el usuario")
                self.assertContains(respuesta, mensaje)
        self.assertFalse(User.objects.filter(email="otro@hotel.cl").exists())

    def test_editar_datos_y_perfil(self):
        otro = crear("pedro", p.ANALISTA)
        respuesta = self.client.post(f"/usuarios/{otro.pk}/", {
            "accion": "datos", "first_name": "Pedro", "last_name": "Soto", "email": "pedro@hotel.cl",
            "perfil": p.CONSULTA, "is_active": "on",
        }, follow=True)
        self.assertContains(respuesta, "Se guardaron los cambios de Pedro Soto.")
        otro = User.objects.get(pk=otro.pk)
        self.assertEqual(p.perfil_de(otro), p.CONSULTA)
        self.assertEqual(otro.email, "pedro@hotel.cl")

    def test_desactivar_impide_iniciar_sesion(self):
        otro = crear("pedro", p.ANALISTA)
        self.client.post(f"/usuarios/{otro.pk}/", {
            "accion": "datos", "first_name": "Pedro", "last_name": "Soto", "email": "pedro@hotel.cl", "perfil": p.ANALISTA,
        })
        self.assertFalse(User.objects.get(pk=otro.pk).is_active)
        self.client.logout()
        respuesta = self.client.post("/usuarios/login/", {"email": "pedro@hotel.cl", "password": CLAVE})
        self.assertContains(respuesta, "Correo o contraseña incorrectos.")

    def test_no_puede_quitarse_admin_ni_desactivarse_a_si_mismo(self):
        self.client.post(f"/usuarios/{self.admin.pk}/", {
            "accion": "datos", "first_name": "Ana", "last_name": "Rojas", "email": "jefa@hotel.cl", "perfil": p.ANALISTA,
        })
        yo = User.objects.get(pk=self.admin.pk)
        self.assertEqual(p.perfil_de(yo), p.ADMINISTRADOR)
        self.assertTrue(yo.is_active)

    def test_el_superusuario_no_puede_desactivarse_a_si_mismo(self):
        raiz = crear("raiz", is_superuser=True)
        self.client.force_login(raiz)
        respuesta = self.client.post(f"/usuarios/{raiz.pk}/", {
            "accion": "datos", "first_name": "R", "last_name": "Z", "email": "raiz@hotel.cl", "perfil": p.ADMINISTRADOR,
        })
        self.assertContains(respuesta, "No puedes desactivar tu propia cuenta.")
        self.assertTrue(User.objects.get(pk=raiz.pk).is_active)

    def test_debe_quedar_un_administrador_activo(self):
        from .forms import UsuarioForm
        datos = {"first_name": "Ana", "last_name": "Rojas", "email": "jefa@hotel.cl", "perfil": p.ANALISTA, "is_active": "on"}
        # Sin otro administrador activo no se le puede quitar el perfil a la única que hay.
        formulario = UsuarioForm(datos, instance=self.admin, editor=None)
        self.assertFalse(formulario.is_valid())
        self.assertIn("Debe quedar al menos un administrador activo.", formulario.non_field_errors())
        # Con otro administrador activo, sí.
        crear("otra", p.ADMINISTRADOR)
        self.assertTrue(UsuarioForm(datos, instance=User.objects.get(pk=self.admin.pk), editor=None).is_valid())

    def test_cambiar_contrasena(self):
        otro = crear("pedro", p.ANALISTA)
        respuesta = self.client.post(f"/usuarios/{otro.pk}/", {
            "accion": "clave", "clave": "Nueva-Clave-2026", "clave_repetida": "Nueva-Clave-2026",
        }, follow=True)
        self.assertContains(respuesta, "Se cambió la contraseña de pedro@hotel.cl.")
        self.assertTrue(User.objects.get(pk=otro.pk).check_password("Nueva-Clave-2026"))

    def test_cambiar_la_propia_contrasena_no_cierra_la_sesion(self):
        self.client.post(f"/usuarios/{self.admin.pk}/", {
            "accion": "clave", "clave": "Nueva-Clave-2026", "clave_repetida": "Nueva-Clave-2026",
        })
        self.assertEqual(self.client.get("/usuarios/").status_code, 200)

    def test_contrasena_que_no_coincide(self):
        otro = crear("pedro", p.ANALISTA)
        respuesta = self.client.post(f"/usuarios/{otro.pk}/", {
            "accion": "clave", "clave": "Nueva-Clave-2026", "clave_repetida": "Otra-Clave-2026",
        })
        self.assertContains(respuesta, "Las contraseñas no coinciden.")
        self.assertTrue(User.objects.get(pk=otro.pk).check_password(CLAVE))

    def test_superusuario_siempre_es_administrador(self):
        raiz = crear("raiz", is_superuser=True)
        pagina = self.client.get(f"/usuarios/{raiz.pk}/")
        self.assertContains(pagina, "Esta cuenta es Superusuario")
        self.assertContains(self.client.get("/usuarios/"), "etiqueta--superusuario\">Superusuario<")
        self.client.force_login(raiz)
        self.assertContains(self.client.get("/"), '<span class="usuario__correo">Superusuario</span>')
        self.client.force_login(self.admin)
        self.client.post(f"/usuarios/{raiz.pk}/", {
            "accion": "datos", "first_name": "R", "last_name": "Z", "email": "raiz@hotel.cl",
            "perfil": p.CONSULTA, "is_active": "on",
        })
        self.assertEqual(p.perfil_de(User.objects.get(pk=raiz.pk)), p.ADMINISTRADOR)

    def test_usuario_que_no_existe(self):
        respuesta = self.client.get("/usuarios/999/", follow=True)
        self.assertRedirects(respuesta, "/usuarios/")
        self.assertContains(respuesta, "Ese usuario no existe.")


class LoginTemaTests(TestCase):
    def test_login_tiene_interruptor_y_parte_en_modo_claro(self):
        pagina = self.client.get("/usuarios/login/")
        self.assertContains(pagina, "data-tema-interruptor")
        self.assertNotContains(pagina, "prefers-color-scheme")
