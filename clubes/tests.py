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
