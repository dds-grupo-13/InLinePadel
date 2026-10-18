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
