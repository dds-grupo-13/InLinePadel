from config.test_utils import BaseAPITestCase
from partidas.models import Lobby
from social.models import Contacto, Invitacion, Notificacion

LOBBIES = "/api/partidas/lobbies/"


class SocialAPITests(BaseAPITestCase):
    def hacer_contactos(self, a, b):
        Contacto.objects.create(jugador=a, contacto=b, estado="ACEPTADO")

    def lobby_de(self, cap, hora=20):
        self.login(cap.usuario)
        return self.client.post(LOBBIES, {"turno": self.turno(self.cancha, hora=hora).pk}, format="json").data["id"]

    def test_contactos_solicitud_y_respuesta(self):
        a, b = self.jugador("a"), self.jugador("b")
        self.login(a.usuario)
        r = self.client.post("/api/social/contactos/", {"contacto": b.pk})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.client.post("/api/social/contactos/", {"contacto": b.pk}).status_code, 400)
        self.assertEqual(self.client.post("/api/social/contactos/", {"contacto": a.pk}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/social/contactos/{r.data['id']}/aceptar/").status_code, 403)
        self.login(b.usuario)
        self.assertEqual(self.client.post(f"/api/social/contactos/{r.data['id']}/aceptar/").data["estado"], "ACEPTADO")
        self.assertTrue(Notificacion.objects.filter(usuario=a.usuario).exists())

    def test_cu03_invitar_y_aceptar(self):
        cap, amigo = self.jugador("cap"), self.jugador("amigo")
        self.hacer_contactos(cap, amigo)
        lobby_id = self.lobby_de(cap)
        r = self.client.post("/api/social/invitaciones/", {"lobby": lobby_id, "receptor": amigo.pk})
        self.assertEqual(r.status_code, 201, r.data)
        self.login(amigo.usuario)
        r2 = self.client.post(f"/api/social/invitaciones/{r.data['id']}/aceptar/")
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(Lobby.objects.get().inscripciones.count(), 2)

    def test_invitar_requiere_contacto_e_inscripcion(self):
        cap, extraño = self.jugador("cap"), self.jugador("extraño")
        lobby_id = self.lobby_de(cap)
        r = self.client.post("/api/social/invitaciones/", {"lobby": lobby_id, "receptor": extraño.pk})
        self.assertEqual(r.status_code, 409)

    def test_rechazar_invitacion_solo_receptor(self):
        cap, amigo = self.jugador("cap"), self.jugador("amigo")
        self.hacer_contactos(cap, amigo)
        lobby_id = self.lobby_de(cap)
        inv = self.client.post("/api/social/invitaciones/", {"lobby": lobby_id, "receptor": amigo.pk}).data["id"]
        self.assertEqual(self.client.post(f"/api/social/invitaciones/{inv}/rechazar/").status_code, 403)
        self.login(amigo.usuario)
        self.assertEqual(self.client.post(f"/api/social/invitaciones/{inv}/rechazar/").data["estado"], "RECHAZADA")

    def test_aceptar_sin_cupos_expira_la_invitacion(self):
        cap, amigo = self.jugador("cap"), self.jugador("amigo")
        self.hacer_contactos(cap, amigo)
        lobby_id = self.lobby_de(cap)
        inv = self.client.post("/api/social/invitaciones/", {"lobby": lobby_id, "receptor": amigo.pk}).data["id"]
        for n in ("j2", "j3", "j4"):
            self.login(self.jugador(n).usuario)
            self.client.post(f"{LOBBIES}{lobby_id}/unirse/")
        self.assertEqual(Invitacion.objects.get(pk=inv).estado, "EXPIRADA")
        self.login(amigo.usuario)
        self.assertEqual(self.client.post(f"/api/social/invitaciones/{inv}/aceptar/").status_code, 409)

    def test_privada_solo_por_invitacion_no_se_puede_solicitar(self):
        cap, visita = self.jugador("cap"), self.jugador("visita")
        self.login(cap.usuario)
        lobby_id = self.client.post(
            LOBBIES, {"turno": self.turno(self.cancha).pk, "privacidad": "PRIVADO"}, format="json"
        ).data["id"]

        self.login(visita.usuario)
        self.assertEqual(self.client.post(f"{LOBBIES}{lobby_id}/unirse/").status_code, 404)
        self.assertEqual(
            self.client.post("/api/social/solicitudes/", {"lobby": lobby_id}).status_code,
            405,
        )
        self.assertEqual(Lobby.objects.get().inscripciones.count(), 1)

    def test_notificaciones_propias_y_marcar_leidas(self):
        a, b = self.jugador("a"), self.jugador("b")
        Notificacion.objects.create(usuario=a.usuario, mensaje="hola")
        Notificacion.objects.create(usuario=b.usuario, mensaje="ajena")
        self.login(a.usuario)
        r = self.client.get("/api/social/notificaciones/")
        self.assertEqual(r.data["count"], 1)
        self.assertEqual(self.client.post("/api/social/notificaciones/marcar_todas_leidas/").data["marcadas"], 1)
