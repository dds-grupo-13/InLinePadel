from config.test_utils import BaseAPITestCase
from clubes.models import Turno


class ClubesAPITests(BaseAPITestCase):
    def test_solo_admin_sistema_crea_club_con_credenciales(self):
        datos = {
            "denominacion": "Club C", "direccion": "Calle 3", "zona": self.zona.pk,
            "admin_username": "adminc", "admin_email": "c@x.com", "admin_password": "clave12345",
        }
        self.login(self.admin)
        self.assertEqual(self.client.post("/api/clubes/clubes/", datos).status_code, 403)
        self.login(self.superadmin)
        r = self.client.post("/api/clubes/clubes/", datos)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(self.client.post(f"/api/clubes/clubes/{r.data['id']}/suspender/").data["estado"] == "SUSPENDIDO")

    def test_admin_de_club_no_opera_sobre_otro_club(self):
        self.login(self.admin)
        r = self.client.post(
            "/api/clubes/turnos/",
            {"cancha": self.otra_cancha.pk, "fecha": "2030-01-01", "hora_inicio": "10:00", "precio": "100"},
        )
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/clubes/canchas/", {"numero": 5, "club": self.otro_club.pk})
        self.assertEqual(r.status_code, 400)

    def test_turno_no_disponible_solo_si_libre(self):
        libre, tomado = self.turno(self.cancha, hora=18), self.turno(self.cancha, hora=20)
        Turno.objects.filter(pk=tomado.pk).update(estado="BLOQUEADO")
        self.login(self.admin)
        self.assertEqual(self.client.post(f"/api/clubes/turnos/{libre.pk}/no_disponible/").status_code, 200)
        self.assertEqual(self.client.post(f"/api/clubes/turnos/{tomado.pk}/no_disponible/").status_code, 409)
        self.assertEqual(self.client.post(f"/api/clubes/turnos/{libre.pk}/disponible/").status_code, 200)

    def test_jugador_solo_ve_turnos_libres_con_filtros_y_paginado(self):
        self.turno(self.cancha, hora=18, precio="3000")
        self.turno(self.cancha, hora=20, precio="9000")
        Turno.objects.filter(hora_inicio="20:00").update(estado="NO_DISPONIBLE")
        self.login(self.jugador("p").usuario)
        r = self.client.get("/api/clubes/turnos/")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(self.client.get("/api/clubes/turnos/?precio_max=1000").data["count"], 0)

    def test_crear_masivo_y_solape(self):
        self.login(self.admin)
        base = {"cancha": self.cancha.pk, "fecha": "2030-01-01", "precio": "100"}
        r = self.client.post(
            "/api/clubes/turnos/crear_masivo/",
            [{**base, "hora_inicio": "10:00"}, {**base, "hora_inicio": "11:30"}],
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.post(
            "/api/clubes/turnos/crear_masivo/",
            [{**base, "hora_inicio": "10:30"}], format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_suspender_club_retira_turnos_libres(self):
        self.turno(self.cancha)
        self.login(self.superadmin)
        self.client.post(f"/api/clubes/clubes/{self.club.pk}/suspender/")
        self.login(self.jugador("q").usuario)
        self.assertEqual(self.client.get("/api/clubes/turnos/").data["count"], 0)

    def test_crear_club_valida_credenciales_del_admin(self):
        self.login(self.superadmin)
        datos = {
            "denominacion": "Club C", "direccion": "Calle 3", "zona": self.zona.pk,
            "admin_username": "adminc", "admin_email": "c@x.com", "admin_password": "clave12345",
        }
        url = "/api/clubes/clubes/"
        r = self.client.post(url, {**datos, "admin_username": "admin_club"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("admin_username", r.data)
        r = self.client.post(url, {**datos, "admin_email": "AC@x.com"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("admin_email", r.data)
        r = self.client.post(url, {**datos, "admin_password": "12345678"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("admin_password", r.data)

    def test_jugador_no_ve_el_admin_del_club(self):
        self.login(self.jugador("p").usuario)
        r = self.client.get("/api/clubes/clubes/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("admin", r.data["results"][0])
        self.login(self.superadmin)
        self.assertIn("admin", self.client.get("/api/clubes/clubes/").data["results"][0])

    def test_crear_masivo_tiene_tope(self):
        self.login(self.admin)
        base = {"cancha": self.cancha.pk, "fecha": "2030-01-01", "precio": "100", "hora_inicio": "10:00"}
        r = self.client.post(
            "/api/clubes/turnos/crear_masivo/", [base] * 501, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Turno.objects.count(), 0)


class CancelarPorClubTests(BaseAPITestCase):
    MOTIVO = {"motivo": "Lluvia: cancha descubierta inhabilitada"}

    def url(self, turno):
        return f"/api/clubes/turnos/{turno.pk}/cancelar_por_club/"

    def partida(self, completa=False):
        from partidas.models import Lobby

        turno = self.turno(self.cancha)
        lobby = Lobby.crear(turno, self.jugador("cap"))
        if completa:
            for nombre in ("j2", "j3", "j4"):
                lobby.inscribir(self.jugador(nombre))
        return turno, lobby

    def test_cancela_una_partida_en_formacion(self):
        from social.models import Notificacion

        turno, lobby = self.partida()
        self.login(self.admin)
        r = self.client.post(self.url(turno), self.MOTIVO, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["estado"], "NO_DISPONIBLE")
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, "CANCELADO")
        self.assertEqual(lobby.cancelada_por, "CLUB")
        self.assertEqual(lobby.motivo_cancelacion, self.MOTIVO["motivo"])
        mensaje = Notificacion.objects.get(usuario__username="cap", mensaje__contains="Club A").mensaje
        self.assertIn(self.MOTIVO["motivo"], mensaje)
        self.assertIn("canceló la partida", mensaje)

    def test_cancela_una_partida_firme_y_avisa_a_los_cuatro(self):
        from datetime import timedelta

        from django.utils import timezone

        from social.models import Notificacion

        turno, lobby = self.partida(completa=True)
        inicio = timezone.now() + timedelta(hours=2)
        Turno.objects.filter(pk=turno.pk).update(inicio=inicio, fin=inicio + timedelta(minutes=90))
        self.login(self.admin)
        r = self.client.post(self.url(turno), self.MOTIVO, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, "CANCELADO")
        avisados = Notificacion.objects.filter(mensaje__contains="canceló la partida")
        self.assertEqual(avisados.count(), 4)
        self.assertEqual(
            self.client.post(f"/api/clubes/turnos/{turno.pk}/disponible/").status_code, 200
        )

    def test_admin_de_otro_club_recibe_404(self):
        turno, _ = self.partida()
        self.login(self.otro_admin)
        self.assertEqual(self.client.post(self.url(turno), self.MOTIVO, format="json").status_code, 404)

    def test_jugador_no_puede(self):
        turno, _ = self.partida()
        self.login(self.jugador("curioso").usuario)
        self.assertEqual(self.client.post(self.url(turno), self.MOTIVO, format="json").status_code, 403)

    def test_sin_partida_da_409(self):
        turno = self.turno(self.cancha, hora=10)
        self.login(self.admin)
        r = self.client.post(self.url(turno), self.MOTIVO, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("No disponible", r.data["detail"])

    def test_turno_pasado_da_400(self):
        turno = self.turno(self.cancha, dias=-2)
        self.login(self.admin)
        self.assertEqual(self.client.post(self.url(turno), self.MOTIVO, format="json").status_code, 400)

    def test_motivo_obligatorio_y_acotado(self):
        turno, lobby = self.partida()
        self.login(self.admin)
        for cuerpo in ({}, {"motivo": "abc"}, {"motivo": "x" * 201}):
            self.assertEqual(self.client.post(self.url(turno), cuerpo, format="json").status_code, 400)
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, "EN_FORMACION")


class OcupacionTests(BaseAPITestCase):
    def test_ocupacion_expone_inicio_y_fin_del_turno(self):
        turno = self.turno(self.cancha)
        self.login(self.admin)
        r = self.client.get(f"/api/clubes/clubes/{self.club.pk}/ocupacion/")
        self.assertEqual(r.status_code, 200)
        fila = next(f for f in r.data["results"] if f["id"] == turno.pk)
        turno.refresh_from_db()
        self.assertEqual(fila["inicio"][:16], turno.inicio.astimezone().isoformat()[:16])
        self.assertIn("fin", fila)
        self.assertTrue(fila["fin"] > fila["inicio"])
