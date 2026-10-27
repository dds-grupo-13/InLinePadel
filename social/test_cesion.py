from datetime import timedelta

from django.utils import timezone

from clubes.models import Turno
from config.test_utils import BaseAPITestCase
from partidas.models import Inscripcion, Lobby
from social.models import Contacto, Invitacion, Notificacion

LOBBIES = "/api/partidas/lobbies/"
INVITACIONES = "/api/social/invitaciones/"


class CesionTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.cap = self.jugador("cap")
        self.j2, self.j3, self.j4 = (self.jugador(n) for n in ("j2", "j3", "j4"))
        self.turno_partida = self.turno(self.cancha)
        self.lobby = Lobby.crear(self.turno_partida, self.cap)
        for j in (self.j2, self.j3, self.j4):
            self.lobby.inscribir(j)
        self.lobby.refresh_from_db()
        self.codigo = self.lobby.codigo_reserva
        self.amigo = self.jugador("amigo")

    def amigos(self, a, b):
        Contacto.objects.create(jugador=a, contacto=b, estado=Contacto.Estado.ACEPTADO)

    def hacer_firme(self):
        inicio = timezone.now() + timedelta(hours=2)
        Turno.objects.filter(pk=self.turno_partida.pk).update(
            inicio=inicio, fin=inicio + timedelta(minutes=90)
        )

    def ceder(self, emisor, receptor):
        self.login(emisor.usuario)
        return self.client.post(
            f"{LOBBIES}{self.lobby.pk}/ceder/", {"receptor": receptor.pk}, format="json"
        )

    def responder(self, receptor, id_invitacion, accion="aceptar"):
        self.login(receptor.usuario)
        return self.client.post(f"{INVITACIONES}{id_invitacion}/{accion}/")

    def test_ceder_despues_del_cierre_conserva_codigo_y_cupo(self):
        self.hacer_firme()
        self.amigos(self.j2, self.amigo)
        cupo = Inscripcion.objects.get(lobby=self.lobby, jugador=self.j2).numero_cupo
        r = self.ceder(self.j2, self.amigo)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data["tipo"], r.data["reemplaza"]), ("CESION", self.j2.pk))
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.amigo.usuario, mensaje__contains="te ofrece su lugar"
            ).exists()
        )
        r = self.responder(self.amigo, r.data["id"])
        self.assertEqual(r.status_code, 200, r.data)
        self.lobby.refresh_from_db()
        self.turno_partida.refresh_from_db()
        self.assertEqual(self.lobby.estado, Lobby.Estado.COMPLETO)
        self.assertEqual(self.lobby.codigo_reserva, self.codigo)
        self.assertEqual(self.turno_partida.estado, Turno.Estado.CONFIRMADO)
        self.assertEqual(Inscripcion.objects.get(lobby=self.lobby, jugador=self.amigo).numero_cupo, cupo)
        self.assertFalse(Inscripcion.objects.filter(lobby=self.lobby, jugador=self.j2).exists())
        self.assertEqual(self.lobby.inscripciones.count(), 4)
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.amigo.usuario, mensaje__contains=self.codigo
            ).exists()
        )
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.cap.usuario, mensaje__contains="reemplaza a j2"
            ).exists()
        )

    def test_ceder_antes_del_cierre_no_reabre_la_partida(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        self.assertEqual(self.responder(self.amigo, invitacion).status_code, 200)
        self.lobby.refresh_from_db()
        self.assertEqual(self.lobby.estado, Lobby.Estado.COMPLETO)

    def test_si_cede_el_capitan_la_capitania_pasa_al_receptor(self):
        self.hacer_firme()
        self.amigos(self.cap, self.amigo)
        invitacion = self.ceder(self.cap, self.amigo).data["id"]
        self.responder(self.amigo, invitacion)
        self.lobby.refresh_from_db()
        self.assertEqual(self.lobby.capitan_id, self.amigo.pk)

    def test_receptor_que_no_es_contacto(self):
        self.assertEqual(self.ceder(self.j2, self.amigo).status_code, 409)

    def test_receptor_ya_inscripto(self):
        self.amigos(self.j2, self.j3)
        self.assertEqual(self.ceder(self.j2, self.j3).status_code, 409)

    def test_receptor_con_superposicion_al_ceder(self):
        self.amigos(self.j2, self.amigo)
        Lobby.crear(self.turno(self.otra_cancha, hora=20), self.amigo)
        r = self.ceder(self.j2, self.amigo)
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("horario", r.data["detail"])

    def test_receptor_con_superposicion_al_aceptar(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        Lobby.crear(self.turno(self.otra_cancha, hora=20), self.amigo)
        r = self.responder(self.amigo, invitacion)
        self.assertEqual(r.status_code, 409, r.data)
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.EXPIRADA)
        self.assertTrue(Inscripcion.objects.filter(lobby=self.lobby, jugador=self.j2).exists())

    def test_doble_cesion_pendiente(self):
        otro = self.jugador("otro")
        self.amigos(self.j2, self.amigo)
        self.amigos(self.j2, otro)
        self.assertEqual(self.ceder(self.j2, self.amigo).status_code, 201)
        self.assertEqual(self.ceder(self.j2, otro).status_code, 409)

    def test_solo_se_cede_en_una_partida_completa(self):
        lobby = Lobby.crear(self.turno(self.cancha, hora=10), self.jugador("c2"))
        self.amigos(lobby.capitan, self.amigo)
        self.login(lobby.capitan.usuario)
        r = self.client.post(f"{LOBBIES}{lobby.pk}/ceder/", {"receptor": self.amigo.pk}, format="json")
        self.assertEqual(r.status_code, 409)

    def test_no_se_puede_cederse_a_uno_mismo(self):
        self.assertEqual(self.ceder(self.j2, self.j2).status_code, 400)

    def test_rechazo_notifica_y_no_cambia_nada(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        self.assertEqual(self.responder(self.amigo, invitacion, "rechazar").status_code, 200)
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.RECHAZADA)
        self.assertTrue(Inscripcion.objects.filter(lobby=self.lobby, jugador=self.j2).exists())
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.j2.usuario, mensaje__contains="rechazó tu invitación"
            ).exists()
        )

    def test_el_emisor_que_se_baja_antes_del_cierre_expira_su_cesion(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        self.lobby.abandonar(self.j2)
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.EXPIRADA)
        self.assertEqual(self.responder(self.amigo, invitacion).status_code, 409)

    def test_si_la_partida_se_reabre_expiran_todas_las_cesiones(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        self.lobby.abandonar(self.j3)
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.EXPIRADA)

    def test_cancelar_la_partida_expira_la_cesion(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        self.lobby._cancelar(Lobby.CanceladaPor.CLUB, "Lluvia fuerte")
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.EXPIRADA)

    def test_check_in_expira_cesiones_pendientes(self):
        self.amigos(self.j2, self.amigo)
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        ahora = timezone.now()
        Lobby.objects.update(plazo_limite=ahora - timedelta(hours=2), fecha_check_in=ahora - timedelta(hours=1))
        self.login(self.admin)
        r = self.client.post(f"{LOBBIES}check_in/", {"codigo_reserva": self.codigo})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Invitacion.objects.get(pk=invitacion).estado, Invitacion.Estado.EXPIRADA)

    def test_receptor_ve_la_partida_completa_pero_no_puede_unirse(self):
        self.amigos(self.j2, self.amigo)
        self.ceder(self.j2, self.amigo)
        self.login(self.amigo.usuario)
        r = self.client.get(f"{LOBBIES}{self.lobby.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["codigo_reserva"])
        self.assertEqual(self.client.post(f"{LOBBIES}{self.lobby.pk}/unirse/").status_code, 409)

    def test_flags_de_cesion(self):
        self.amigos(self.j2, self.amigo)
        self.login(self.j2.usuario)
        d = self.client.get(f"{LOBBIES}{self.lobby.pk}/").data
        self.assertTrue(d["puede_ceder"])
        self.assertIsNone(d["cesion_pendiente"])
        invitacion = self.ceder(self.j2, self.amigo).data["id"]
        d = self.client.get(f"{LOBBIES}{self.lobby.pk}/").data
        self.assertFalse(d["puede_ceder"])
        self.assertEqual(d["cesion_pendiente"], {"id": invitacion, "receptor": self.amigo.pk})
        self.login(self.j3.usuario)
        d = self.client.get(f"{LOBBIES}{self.lobby.pk}/").data
        self.assertTrue(d["puede_ceder"])
        self.assertIsNone(d["cesion_pendiente"])
        self.login(self.amigo.usuario)
        d = self.client.get(f"{LOBBIES}{self.lobby.pk}/").data
        self.assertFalse(d["puede_ceder"])

    def test_la_cesion_no_se_crea_por_el_endpoint_de_invitaciones(self):
        self.amigos(self.j2, self.amigo)
        self.login(self.j2.usuario)
        r = self.client.post(
            INVITACIONES,
            {"lobby": self.lobby.pk, "receptor": self.amigo.pk, "reemplaza": self.j2.pk},
            format="json",
        )
        self.assertIn(r.status_code, (400, 409))
        self.assertFalse(Invitacion.objects.exists())

    def test_abandonar_firme_sugiere_ceder(self):
        self.hacer_firme()
        self.login(self.j2.usuario)
        r = self.client.post(f"{LOBBIES}{self.lobby.pk}/abandonar/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("ceder tu lugar", r.data["detail"])
