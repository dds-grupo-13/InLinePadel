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
        r = self.crear(j, self.turno(self.otra_cancha, hora=20))
        self.assertEqual(r.status_code, 409)
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
        self.login(self.jugador("j5").usuario)
        self.assertIn(self.client.post(f"{URL}{lobby_id}/unirse/").status_code, (404, 409))
        self.assertEqual(Lobby.objects.get().inscripciones.count(), 4)
        self.login(self.admin)
        codigo = Lobby.objects.get().codigo_reserva
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 409)
        self.habilitar_check_in()
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 200)
        self.assertEqual(self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 409)
        t.refresh_from_db()
        self.assertEqual(t.estado, "CUMPLIDO")

    def test_estado_de_reserva_en_ocupacion_y_detalle_hasta_cumplida(self):
        t = self.turno(self.cancha)
        lobby_id = self.crear(self.jugador("cap"), t).data["id"]
        ocupacion = f"/api/clubes/clubes/{self.club.pk}/ocupacion/"

        def reserva_en_ocupacion():
            self.login(self.admin)
            fila = next(
                f for f in self.client.get(ocupacion).data["results"] if f["id"] == t.pk
            )
            return fila["lobby"]["reserva"]

        self.assertEqual(reserva_en_ocupacion(), "PROVISORIA")
        jugadores = [self.jugador(n) for n in ("j2", "j3", "j4")]
        for j in jugadores:
            self.login(j.usuario)
            self.client.post(f"{URL}{lobby_id}/unirse/")
        self.assertEqual(reserva_en_ocupacion(), "CONFIRMADA")

        codigo = Lobby.objects.get().codigo_reserva
        self.habilitar_check_in()
        self.login(self.admin)
        self.assertEqual(
            self.client.post(f"{URL}check_in/", {"codigo_reserva": codigo}).status_code, 200
        )
        self.assertEqual(reserva_en_ocupacion(), "CUMPLIDA")

        self.login(jugadores[0].usuario)
        detalle = self.client.get(f"{URL}{lobby_id}/").data
        self.assertEqual(detalle["estado"], "JUGADO")
        self.assertEqual(detalle["estado_reserva"], "CUMPLIDA")
        self.assertEqual(detalle["mensaje_reserva"], "Partido jugado — reserva cumplida")
        self.assertEqual(detalle["codigo_reserva"], codigo)

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

    def test_estado_multiple_y_orden_por_inicio(self):
        cap = self.jugador("cap")
        ids = {}
        for h in (8, 12, 16):
            ids[h] = self.crear(cap if h < 16 else self.jugador("cap2"), self.turno(self.cancha, hora=h)).data["id"]
        Lobby.objects.filter(pk=ids[12]).update(estado="COMPLETO")
        Lobby.objects.filter(pk=ids[16]).update(estado="CANCELADO")
        self.login(cap.usuario)

        def listar(query):
            return [l["id"] for l in self.client.get(f"{URL}?{query}").data["results"]]

        self.assertEqual(listar("estado=EN_FORMACION"), [ids[8]])
        self.assertEqual(listar("estado=EN_FORMACION&estado=COMPLETO"), [ids[8], ids[12]])
        self.assertEqual(listar("estado=EN_FORMACION&estado=COMPLETO&orden=-inicio"), [ids[12], ids[8]])
        self.assertEqual(listar("estado=COMPLETO&estado=EN_FORMACION&orden=inicio"), [ids[8], ids[12]])

    def test_resumen_por_club(self):
        resumen = f"{URL}resumen_por_club/"
        j2, j3 = self.jugador("j2"), self.jugador("j3")
        visitante = self.jugador("visita")
        # Club A: dos públicos (uno con 2 inscriptos), uno privado sin invitación,
        # uno privado con invitación y uno donde el visitante ya está inscripto.
        cercano = self.crear(j2, self.turno(self.cancha, dias=2, hora=8)).data["id"]
        lejano = self.crear(j3, self.turno(self.cancha, dias=4, hora=12)).data["id"]
        Lobby.objects.get(pk=lejano).inscribir(self.jugador("extra"))
        self.crear(self.jugador("p1"), self.turno(self.cancha, dias=5, hora=16), privacidad="PRIVADO")
        cap_privado = self.jugador("p2")
        privado_invitado = self.crear(
            cap_privado, self.turno(self.cancha, dias=6, hora=8), privacidad="PRIVADO"
        ).data["id"]
        Invitacion.objects.create(
            lobby=Lobby.objects.get(pk=privado_invitado), emisor=cap_privado, receptor=visitante
        )
        propio = self.crear(visitante, self.turno(self.cancha, dias=7, hora=8)).data["id"]
        # Club B: uno caro y uno completo.
        caro = self.crear(self.jugador("c1"), self.turno(self.otra_cancha, dias=2, hora=9, precio="20000")).data["id"]
        completo = self.crear(self.jugador("c2"), self.turno(self.otra_cancha, dias=3, hora=9)).data["id"]
        for n in ("k1", "k2", "k3"):
            Lobby.objects.get(pk=completo).inscribir(self.jugador(n))

        self.login(visitante.usuario)
        r = self.client.get(resumen)
        self.assertEqual(r.status_code, 200, r.data)
        por_club = {f["club"]: f for f in r.data}
        self.assertEqual(set(por_club), {self.club.pk, self.otro_club.pk})
        a = por_club[self.club.pk]
        # cercano (3 libres) + lejano (2 libres) + privado invitado (3 libres);
        # sin el privado sin invitación ni el propio.
        self.assertEqual(
            (a["disponibles"], a["cupos_libres"], a["invitaciones"]), (3, 8, 1)
        )
        self.assertEqual(a["proximo"]["id"], cercano)
        self.assertEqual(
            set(a["proximo"]), {"id", "fecha", "hora_inicio", "inicio"}
        )
        b = por_club[self.otro_club.pk]
        self.assertEqual((b["disponibles"], b["cupos_libres"], b["invitaciones"]), (1, 3, 0))
        self.assertEqual(b["proximo"]["id"], caro)

        # Filtros de LobbyFilter.
        r = self.client.get(f"{resumen}?club={self.otro_club.pk}")
        self.assertEqual([f["club"] for f in r.data], [self.otro_club.pk])
        r = self.client.get(f"{resumen}?precio_max=1500")
        self.assertEqual([f["club"] for f in r.data], [self.club.pk])
        r = self.client.get(f"{resumen}?hora_desde=10:00")
        self.assertEqual(
            (r.data[0]["disponibles"], r.data[0]["proximo"]["id"]), (1, lejano)
        )
        r = self.client.get(f"{resumen}?zona={self.zona.pk + 100}")
        self.assertEqual(r.data, [])
        self.assertNotIn(propio, [f["proximo"]["id"] for f in self.client.get(resumen).data])

    def test_resumen_por_club_exige_autenticacion(self):
        self.assertEqual(self.client.get(f"{URL}resumen_por_club/").status_code, 401)

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
