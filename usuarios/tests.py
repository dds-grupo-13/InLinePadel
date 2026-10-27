from config.test_utils import BaseAPITestCase


class UsuariosAPITests(BaseAPITestCase):
    def login_jwt(self, username="ana", password="clave12345"):
        r = self.client.post(
            "/api/usuarios/auth/login/", {"username": username, "password": password}
        )
        if r.status_code == 200:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return r

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

        r = self.login_jwt()
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertEqual(r.data["usuario"]["username"], "ana")
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
        self.assertEqual(self.client.get("/api/partidas/lobbies/").status_code, 401)
        self.assertEqual(self.client.get("/api/clubes/turnos/").status_code, 401)

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

    def test_cambio_de_password_pide_la_actual_y_mantiene_el_acceso(self):
        self.jugador("ana")
        self.login_jwt()
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
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(
            url, {"usuario": {"password": "otraclave987", "password_actual": "clave12345"}}, format="json"
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.credentials()
        r = self.login_jwt(password="otraclave987")
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
        self.assertEqual(Lobby.objects.get(pk=con_otro).capitan_id, otro.pk)
        self.assertEqual(Lobby.objects.get(turno=solo).estado, "CANCELADO")
        self.assertFalse(Lobby.objects.get(pk=con_otro).inscripciones.filter(jugador=cap).exists())
        self.assertEqual(SolicitudAcceso.objects.count(), 0)


    def test_no_se_da_de_baja_con_una_reserva_firme(self):
        from datetime import timedelta

        from django.utils import timezone

        from clubes.models import Turno
        from partidas.models import Lobby

        cap = self.jugador("cap")
        lobby = Lobby.crear(self.turno(self.cancha), cap)
        for nombre in ("j2", "j3", "j4"):
            lobby.inscribir(self.jugador(nombre))
        inicio = timezone.now() + timedelta(hours=2)
        Turno.objects.filter(pk=lobby.turno_id).update(
            inicio=inicio, fin=inicio + timedelta(minutes=90)
        )

        self.login(cap.usuario)
        r = self.client.delete(f"/api/usuarios/jugadores/{cap.pk}/")
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("Club A", r.data["detail"])
        cap.usuario.refresh_from_db()
        self.assertTrue(cap.usuario.is_active)
        self.assertTrue(lobby.inscripciones.filter(jugador=cap).exists())

    def test_baja_con_reserva_no_firme_se_baja_de_la_partida(self):
        from partidas.models import Lobby

        cap = self.jugador("cap")
        lobby = Lobby.crear(self.turno(self.cancha), cap)
        for nombre in ("j2", "j3", "j4"):
            lobby.inscribir(self.jugador(nombre))
        self.login(cap.usuario)
        self.assertEqual(self.client.delete(f"/api/usuarios/jugadores/{cap.pk}/").status_code, 204)
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, "EN_FORMACION")


class JWTTests(BaseAPITestCase):
    ME = "/api/usuarios/jugadores/me/"

    def setUp(self):
        super().setUp()
        self.jugador("ana")
        self.tokens = self.client.post(
            "/api/usuarios/auth/login/", {"username": "ana", "password": "clave12345"}
        ).data

    def bearer(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_protegido_sin_token_token_valido_y_falso(self):
        self.assertEqual(self.client.get(self.ME).status_code, 401)
        self.bearer(self.tokens["access"])
        self.assertEqual(self.client.get(self.ME).status_code, 200)
        self.bearer("token.falso.x")
        self.assertEqual(self.client.get(self.ME).status_code, 401)

    def test_access_vencido_da_401(self):
        from datetime import timedelta

        from rest_framework_simplejwt.tokens import AccessToken

        token = AccessToken(self.tokens["access"])
        token.set_exp(lifetime=-timedelta(seconds=1))
        self.bearer(str(token))
        self.assertEqual(self.client.get(self.ME).status_code, 401)

    def test_login_no_crea_sesion(self):
        self.assertNotIn("sessionid", self.client.cookies)

    def test_refresh_rota_y_el_viejo_queda_invalido(self):
        url = "/api/usuarios/auth/refresh/"
        r = self.client.post(url, {"refresh": self.tokens["refresh"]})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        r = self.client.post(url, {"refresh": self.tokens["refresh"]})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.post(url, {"refresh": "falso"}).status_code, 401)

    def test_logout_invalida_el_refresh(self):
        self.bearer(self.tokens["access"])
        r = self.client.post("/api/usuarios/auth/logout/", {"refresh": self.tokens["refresh"]})
        self.assertEqual(r.status_code, 204)
        self.client.credentials()
        r = self.client.post("/api/usuarios/auth/refresh/", {"refresh": self.tokens["refresh"]})
        self.assertEqual(r.status_code, 401)

    def test_logout_exige_token_y_refresh_valido(self):
        url = "/api/usuarios/auth/logout/"
        self.assertEqual(self.client.post(url, {"refresh": self.tokens["refresh"]}).status_code, 401)
        self.bearer(self.tokens["access"])
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.client.post(url, {"refresh": "falso"}).status_code, 400)

    def test_baja_invalida_los_refresh(self):
        self.bearer(self.tokens["access"])
        self.assertEqual(self.client.delete(f"/api/usuarios/jugadores/{self.client.get(self.ME).data['id']}/").status_code, 204)
        self.client.credentials()
        r = self.client.post("/api/usuarios/auth/refresh/", {"refresh": self.tokens["refresh"]})
        self.assertEqual(r.status_code, 401)

    def test_cors_preflight(self):
        url = "/api/clubes/clubes/"
        pedido = {
            "HTTP_ACCESS_CONTROL_REQUEST_METHOD": "GET",
            "HTTP_ACCESS_CONTROL_REQUEST_HEADERS": "authorization,content-type",
        }
        r = self.client.options(url, HTTP_ORIGIN="http://localhost:4200", **pedido)
        self.assertEqual(r["Access-Control-Allow-Origin"], "http://localhost:4200")
        self.assertIn("authorization", r["Access-Control-Allow-Headers"])
        r = self.client.options(url, HTTP_ORIGIN="http://malo.com", **pedido)
        self.assertNotIn("Access-Control-Allow-Origin", r)
