from django.db import IntegrityError, transaction

from clubes.models import Turno
from config.test_utils import BaseAPITestCase
from partidas.models import Lobby
from social.models import Invitacion, Notificacion, SolicitudAcceso
from usuarios.models import Jugador, Usuario


class UsuarioTests(BaseAPITestCase):
    def test_email_unico(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create_user("otro", "ac@x.com", "clave12345")

    def test_create_user_hashea_la_password(self):
        usuario = Usuario.objects.get(username="admin_club")
        self.assertNotEqual(usuario.password, "clave12345")
        self.assertTrue(usuario.check_password("clave12345"))


class JugadorTests(BaseAPITestCase):
    def test_str_es_el_username(self):
        self.assertEqual(str(self.jugador("pepe")), "pepe")

    def test_valores_por_defecto(self):
        jugador = self.jugador("pepe")
        self.assertEqual(jugador.posicion, Jugador.Posiciones.INDISTINTO)
        self.assertIsNone(jugador.zona)

    def test_la_pk_es_el_usuario(self):
        jugador = self.jugador("pepe")
        self.assertEqual(jugador.pk, jugador.usuario_id)

    def test_borrar_la_zona_deja_al_jugador_sin_zona(self):
        jugador = self.jugador("pepe")
        jugador.zona = self.zona
        jugador.save()
        self.zona.clubes.all().delete()
        self.zona.delete()
        jugador.refresh_from_db()
        self.assertIsNone(jugador.zona)


class DarDeBajaTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.pepe = self.jugador("pepe")
        self.ana = self.jugador("ana")

    def test_desactiva_al_usuario(self):
        self.pepe.dar_de_baja()
        self.pepe.usuario.refresh_from_db()
        self.assertFalse(self.pepe.usuario.is_active)

    def test_sale_de_los_lobbies_vigentes(self):
        lobby = Lobby.crear(self.turno(self.cancha), self.ana)
        lobby.inscribir(self.pepe)
        self.pepe.dar_de_baja()
        self.assertFalse(lobby.inscripciones.filter(jugador=self.pepe).exists())

    def test_notifica_a_los_demas_inscriptos(self):
        lobby = Lobby.crear(self.turno(self.cancha), self.ana)
        lobby.inscribir(self.pepe)
        self.pepe.dar_de_baja()
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.ana.usuario, mensaje="pepe abandonó la partida."
            ).exists()
        )

    def test_capitan_cede_la_capitania(self):
        lobby = Lobby.crear(self.turno(self.cancha), self.pepe)
        lobby.inscribir(self.ana)
        self.pepe.dar_de_baja()
        lobby.refresh_from_db()
        self.assertEqual(lobby.capitan, self.ana)

    def test_capitan_solo_cancela_el_lobby_y_libera_el_turno(self):
        turno = self.turno(self.cancha)
        lobby = Lobby.crear(turno, self.pepe)
        self.pepe.dar_de_baja()
        lobby.refresh_from_db()
        turno.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
        self.assertEqual(turno.estado, Turno.Estado.LIBRE)

    def test_vence_invitaciones_y_solicitudes_pendientes(self):
        privado = Lobby.crear(
            self.turno(self.cancha), self.ana, privacidad=Lobby.Privacidad.PRIVADO
        )
        invitacion = Invitacion.objects.create(lobby=privado, emisor=self.ana, receptor=self.pepe)
        otro_privado = Lobby.crear(
            self.turno(self.cancha, dias=5),
            self.ana,
            privacidad=Lobby.Privacidad.PRIVADO,
        )
        solicitud = SolicitudAcceso.objects.create(lobby=otro_privado, jugador=self.pepe)
        self.pepe.dar_de_baja()
        invitacion.refresh_from_db()
        solicitud.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.EXPIRADA)
        self.assertEqual(solicitud.estado, SolicitudAcceso.Estado.EXPIRADA)

    def test_no_toca_los_pedidos_de_otros(self):
        privado = Lobby.crear(
            self.turno(self.cancha), self.ana, privacidad=Lobby.Privacidad.PRIVADO
        )
        otro = self.jugador("otro")
        invitacion = Invitacion.objects.create(lobby=privado, emisor=self.ana, receptor=otro)
        self.pepe.dar_de_baja()
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.PENDIENTE)

    def test_conserva_el_perfil_de_jugador(self):
        self.pepe.dar_de_baja()
        self.assertTrue(Jugador.objects.filter(pk=self.pepe.pk).exists())
