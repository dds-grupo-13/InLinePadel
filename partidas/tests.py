from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.utils import timezone

from clubes.models import Turno
from config.test_utils import BaseAPITestCase
from partidas.models import Lobby
from social.models import Invitacion, SolicitudAcceso

URL = "/api/partidas/lobbies/"


class LobbyAPITests(BaseAPITestCase):
    @staticmethod
    def habilitar_check_in():
        ahora = timezone.now()
        Lobby.objects.update(
            plazo_limite=ahora - timedelta(hours=2), fecha_check_in=ahora - timedelta(hours=1)
        )

    def crear(self, jugador, turno, **extra):
        self.login(jugador.usuario)
        return self.client.post(URL, {"turno": turno.pk, **extra}, format="json")

    def test_cu01_crea_lobby_y_bloquea_turno(self):
        j, t = self.jugador("cap"), self.turno(self.cancha)
        r = self.crear(j, t)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["estado_reserva"], "PROVISORIA")
        self.assertEqual(r.data["cupos_libres"], 3)
        self.assertEqual(r.data["precio_por_jugador"], "1000.00")
        t.refresh_from_db()
        self.assertEqual(t.estado, "BLOQUEADO")
        lobby = Lobby.objects.get()
        horas = (lobby.plazo_limite - lobby.fecha_creacion).total_seconds() / 3600
        self.assertAlmostEqual(horas, 48, delta=0.1)

    def test_turno_ya_tomado_da_409(self):
        t = self.turno(self.cancha)
        self.assertEqual(self.crear(self.jugador("a"), t).status_code, 201)
        r = self.crear(self.jugador("b"), t)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Lobby.objects.count(), 1)

    def test_limite_de_dos_lobbies_y_solape(self):
        j = self.jugador("cap")
        self.assertEqual(self.crear(j, self.turno(self.cancha, hora=10)).status_code, 201)
        self.assertEqual(self.crear(j, self.turno(self.cancha, hora=14)).status_code, 201)
        self.assertEqual(self.crear(j, self.turno(self.cancha, hora=18)).status_code, 400)

    def test_solape_horario_del_mismo_jugador(self):
        j = self.jugador("cap")
        self.assertEqual(self.crear(j, self.turno(self.cancha, hora=20)).status_code, 201)
        # otra cancha, mismo día y hora → el jugador ya juega en ese horario
        r = self.crear(j, self.turno(self.otra_cancha, hora=20))
        self.assertEqual(r.status_code, 400)
        self.assertIn("horario", str(r.data))

    def test_cu02_unirse_hasta_completar_confirma_reserva(self):
        t = self.turno(self.cancha)
        lobby_id = self.crear(self.jugador("cap"), t).data["id"]
        for n in ("j2", "j3"):
            self.login(self.jugador(n).usuario)
            r = self.client.post(f"{URL}{lobby_id}/unirse/")
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data["estado_reserva"], "PROVISORIA")
        ultimo = self.jugador("j4")
        self.login(ultimo.usuario)
        r = self.client.post(f"{URL}{lobby_id}/unirse/")
        self.assertEqual(r.data["estado_reserva"], "CONFIRMADA")
        self.assertRegex(r.data["codigo_reserva"], r"^[0-9A-F]{4}-[0-9A-F]{4}$")
        t.refresh_from_db()
        self.assertEqual(t.estado, "CONFIRMADO")
        # el quinto jugador ve el lobby completo (404 por no estar en la oferta) y no entra
        self.login(self.jugador("j5").usuario)
        self.assertIn(self.client.post(f"{URL}{lobby_id}/unirse/").status_code, (404, 409))
        self.assertEqual(Lobby.objects.get().inscripciones.count(), 4)
        # el club valida el código (recién cuando se habilita el check-in)
        self.login(self.admin)
        codigo = Lobby.objects.get().codigo_reserva
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 409)
        self.habilitar_check_in()
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 200)
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 409)
        t.refresh_from_db()
        self.assertEqual(t.estado, "CUMPLIDO")

    def test_check_in_de_otro_club_no_funciona(self):
        t = self.turno(self.cancha)
        lobby_id = self.crear(self.jugador("cap"), t).data["id"]
        for n in ("j2", "j3", "j4"):
            self.login(self.jugador(n).usuario)
            self.client.post(f"{URL}{lobby_id}/unirse/")
        codigo = Lobby.objects.get().codigo_reserva
        self.login(self.otro_admin)
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 404)

    def test_lobby_privado_solo_por_invitacion(self):
        t = self.turno(self.cancha)
        lobby_id = self.crear(self.jugador("cap"), t, privacidad="PRIVADO").data["id"]
        self.login(self.jugador("visita").usuario)

        listado = self.client.get(URL)
        ids = [lobby["id"] for lobby in listado.data["results"]]
        self.assertNotIn(lobby_id, ids)
        self.assertEqual(self.client.post(f"{URL}{lobby_id}/unirse/").status_code, 404)
        self.assertFalse(SolicitudAcceso.objects.exists())

    def test_lobby_privado_invitado_aparece_y_se_une(self):
        cap = self.jugador("cap")
        visita = self.jugador("visita")
        t = self.turno(self.cancha)
        lobby_id = self.crear(cap, t, privacidad="PRIVADO").data["id"]
        lobby = Lobby.objects.get(pk=lobby_id)
        invitacion = Invitacion.objects.create(lobby=lobby, emisor=cap, receptor=visita)

        self.login(visita.usuario)
        listado = self.client.get(URL)
        fila = next(lobby for lobby in listado.data["results"] if lobby["id"] == lobby_id)
        self.assertTrue(fila["fui_invitado"])

        r = self.client.post(f"{URL}{lobby_id}/unirse/")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["cupos_ocupados"], 2)
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, "ACEPTADA")

    def test_solo_capitan_cancela_y_libera_turno(self):
        t = self.turno(self.cancha)
        cap = self.jugador("cap")
        lobby_id = self.crear(cap, t).data["id"]
        self.login(self.jugador("otro").usuario)
        self.assertEqual(self.client.delete(f"{URL}{lobby_id}/").status_code, 403)
        self.login(cap.usuario)
        self.assertEqual(self.client.delete(f"{URL}{lobby_id}/").status_code, 204)
        t.refresh_from_db()
        self.assertEqual(t.estado, "LIBRE")

    def test_busqueda_filtros_y_paginado(self):
        for h in range(8, 24, 2):
            self.crear(self.jugador(f"c{h}"), self.turno(self.cancha, hora=h, precio="4000"))
        self.crear(self.jugador("caro"), self.turno(self.otra_cancha, hora=9, precio="20000"))
        self.login(self.jugador("busca").usuario)
        r = self.client.get(URL)
        self.assertEqual(r.data["count"], 9)
        self.assertEqual(len(r.data["results"]), 9)
        self.assertEqual(self.client.get(f"{URL}?precio_max=1500").data["count"], 8)
        self.assertEqual(self.client.get(f"{URL}?club={self.otro_club.pk}").data["count"], 1)
        self.assertEqual(self.client.get(f"{URL}?hora_desde=16:00").data["count"], 4)

    def test_comando_vence_lobbies_y_libera_turno(self):
        t = self.turno(self.cancha)
        self.crear(self.jugador("cap"), t)
        Lobby.objects.update(plazo_limite=timezone.now() - timedelta(minutes=1))
        call_command("vencer_lobbies", stdout=StringIO())
        self.assertEqual(Lobby.objects.get().estado, "CANCELADO")
        t.refresh_from_db()
        self.assertEqual(t.estado, "LIBRE")

    def test_no_se_reserva_turno_pasado_ni_cancha_inactiva(self):
        pasado = self.turno(self.cancha, dias=-3)
        r = self.crear(self.jugador("a"), pasado)
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(Turno.objects.get(pk=pasado.pk).estado, "LIBRE")

        inactiva = self.turno(self.cancha, hora=10)
        self.cancha.activa = False
        self.cancha.save()
        self.assertEqual(self.crear(self.jugador("b"), inactiva).status_code, 400)
        self.assertEqual(Lobby.objects.count(), 0)

    def test_check_in_con_body_invalido_da_400(self):
        self.login(self.admin)
        r = self.client.post(f"{URL}check_in/", [1, 2], format="json")
        self.assertEqual(r.status_code, 400)

    def test_abandonar_lobby_completo_concede_plazo_minimo(self):
        lobby_id = self.crear(self.jugador("cap"), self.turno(self.cancha)).data["id"]
        for n in ("j2", "j3", "j4"):
            self.login(self.jugador(n).usuario)
            self.client.post(f"{URL}{lobby_id}/unirse/")
        Lobby.objects.update(plazo_limite=timezone.now() - timedelta(hours=1))
        self.client.post(f"{URL}{lobby_id}/abandonar/")
        lobby = Lobby.objects.get()
        self.assertEqual(lobby.estado, "EN_FORMACION")
        self.assertGreater(lobby.plazo_limite, timezone.now() + timedelta(hours=11))
        self.assertLessEqual(lobby.plazo_limite, lobby.fecha_check_in)
        call_command("vencer_lobbies", stdout=StringIO())
        self.assertEqual(Lobby.objects.get().estado, "EN_FORMACION")

    def test_valueerror_inesperado_no_se_disfraza_de_400(self):
        from config.exceptions import manejador_excepciones

        self.assertIsNone(manejador_excepciones(ValueError("bug"), {}))
