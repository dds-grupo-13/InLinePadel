from config.test_utils import BaseAPITestCase


class UsuariosAPITests(BaseAPITestCase):
    def test_registro_login_y_perfil(self):
        r = self.client.post(
            "/api/usuarios/jugadores/",
            {
                "usuario": {"username": "ana", "email": "ana@x.com", "password": "clave12345"},
                "posicion": "DRIVE",
                "zona": self.zona.pk,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn("password", r.data["usuario"])

        r = self.client.post(
            "/api/usuarios/auth/login/", {"username": "ana", "password": "clave12345"}
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/usuarios/jugadores/me/")
        self.assertEqual(r.data["jugador"]["posicion"], "DRIVE")

    def test_password_corta_se_rechaza(self):
        r = self.client.post(
            "/api/usuarios/jugadores/",
            {"usuario": {"username": "x", "email": "x@x.com", "password": "123"}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_login_incorrecto_y_throttling(self):
        for _ in range(10):
            r = self.client.post("/api/usuarios/auth/login/", {"username": "n", "password": "m"})
            self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/usuarios/auth/login/", {"username": "n", "password": "m"})
        self.assertEqual(r.status_code, 429)

    def test_no_puede_modificar_perfil_ajeno(self):
        a, b = self.jugador("a"), self.jugador("b")
        self.login(a.usuario)
        r = self.client.patch(f"/api/usuarios/jugadores/{b.pk}/", {"posicion": "REVES"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_endpoints_exigen_autenticacion(self):
        self.assertEqual(self.client.get("/api/partidas/lobbies/").status_code, 403)
        self.assertEqual(self.client.get("/api/clubes/turnos/").status_code, 403)

    def registrar(self, usuario):
        r = self.client.post(
            "/api/usuarios/jugadores/", {"usuario": usuario, "posicion": "DRIVE"}, format="json"
        )
        return r

    def test_password_debil_se_rechaza(self):
        for clave in ("12345678", "password"):
            r = self.registrar({"username": "ana", "email": "ana@x.com", "password": clave})
            self.assertEqual(r.status_code, 400, clave)
            self.assertIn("password", r.data["usuario"])

    def test_email_duplicado_sin_importar_mayusculas(self):
        self.assertEqual(
            self.registrar({"username": "u1", "email": "u@x.com", "password": "clave12345"}).status_code, 201
        )
        r = self.registrar({"username": "u2", "email": "U@X.com", "password": "clave12345"})
        self.assertEqual(r.status_code, 400)

    def test_patch_me_con_mismos_username_y_email(self):
        j = self.jugador("ana")
        self.login(j.usuario)
        r = self.client.patch(
            "/api/usuarios/jugadores/me/",
            {"usuario": {"username": "ana", "email": "ana@x.com", "first_name": "Ana"}},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.data)
        j.usuario.refresh_from_db()
        self.assertEqual(j.usuario.first_name, "Ana")

    def test_patch_me_no_pisa_username_de_otro(self):
        self.jugador("otro")
        self.login(self.jugador("ana").usuario)
        r = self.client.patch(
            "/api/usuarios/jugadores/me/", {"usuario": {"username": "otro"}}, format="json"
        )
        self.assertEqual(r.status_code, 400)

    def test_cambio_de_password_pide_la_actual_y_mantiene_la_sesion(self):
        self.jugador("ana")
        self.client.post("/api/usuarios/auth/login/", {"username": "ana", "password": "clave12345"})
        url = "/api/usuarios/jugadores/me/"
        r = self.client.patch(url, {"usuario": {"password": "otraclave987"}}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(
            url, {"usuario": {"password": "otraclave987", "password_actual": "incorrecta"}}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(
            url, {"usuario": {"password": "12345678", "password_actual": "clave12345"}}, format="json"
        )
        self.assertEqual(r.status_code, 400)  # no pasa los validadores
        r = self.client.patch(
            url, {"usuario": {"password": "otraclave987", "password_actual": "clave12345"}}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        # la sesión sigue viva tras el cambio
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post("/api/usuarios/auth/logout/")
        r = self.client.post("/api/usuarios/auth/login/", {"username": "ana", "password": "otraclave987"})
        self.assertEqual(r.status_code, 200)

    def test_dar_de_baja_libera_partidas_y_cupos(self):
        from partidas.models import Lobby
        from social.models import SolicitudAcceso

        cap, otro = self.jugador("cap"), self.jugador("otro")
        t = self.turno(self.cancha)
        solo = self.turno(self.cancha, hora=10)
        self.login(cap.usuario)
        con_otro = self.client.post("/api/partidas/lobbies/", {"turno": t.pk}, format="json").data["id"]
        self.client.post("/api/partidas/lobbies/", {"turno": solo.pk}, format="json")
        self.login(otro.usuario)
        self.client.post(f"/api/partidas/lobbies/{con_otro}/unirse/")

        self.login(cap.usuario)
        self.assertEqual(self.client.delete(f"/api/usuarios/jugadores/{cap.pk}/").status_code, 204)
        cap.usuario.refresh_from_db()
        self.assertFalse(cap.usuario.is_active)
        # la capitanía pasó al otro jugador y el lobby en solitario se canceló
        self.assertEqual(Lobby.objects.get(pk=con_otro).capitan_id, otro.pk)
        self.assertEqual(Lobby.objects.get(turno=solo).estado, "CANCELADO")
        self.assertFalse(Lobby.objects.get(pk=con_otro).inscripciones.filter(jugador=cap).exists())
        self.assertEqual(SolicitudAcceso.objects.count(), 0)
