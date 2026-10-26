from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from clubes.models import Turno
from config.exceptions import Conflicto
from config.test_utils import BaseAPITestCase
from partidas.models import Lobby
from social.models import Contacto, Invitacion, Notificacion, SolicitudAcceso


class SocialBaseTestCase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.capitan = self.jugador("capitan")
        self.otro = self.jugador("otro")
        self.publico = Lobby.crear(self.turno(self.cancha, dias=3, hora=20), self.capitan)
        self.privado = Lobby.crear(
            self.turno(self.cancha, dias=4, hora=20),
            self.capitan,
            privacidad=Lobby.Privacidad.PRIVADO,
        )

    def llenar(self, lobby, hasta=3):
        for i in range(hasta):
            lobby.inscribir(self.jugador(f"relleno{lobby.pk}_{i}"))


class NotificacionTests(BaseAPITestCase):
    def test_str_y_valores_por_defecto(self):
        notificacion = Notificacion.objects.create(usuario=self.admin, mensaje="hola")
        self.assertFalse(notificacion.leida)
        self.assertEqual(str(notificacion), f"Notificación para {self.admin.pk}")

    def test_se_borran_con_el_usuario(self):
        Notificacion.objects.create(usuario=self.otro_admin, mensaje="hola")
        self.otro_admin.clubes_administrados.all().delete()
        self.otro_admin.delete()
        self.assertFalse(Notificacion.objects.exists())


class ContactoTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.a = self.jugador("a")
        self.b = self.jugador("b")

    def test_estado_inicial_pendiente(self):
        contacto = Contacto.objects.create(jugador=self.a, contacto=self.b)
        self.assertEqual(contacto.estado, Contacto.Estado.PENDIENTE)

    def test_str(self):
        contacto = Contacto.objects.create(jugador=self.a, contacto=self.b)
        self.assertEqual(str(contacto), f"{self.a.pk} -> {self.b.pk} (PENDIENTE)")

    def test_no_puede_agregarse_a_si_mismo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contacto.objects.create(jugador=self.a, contacto=self.a)

    def test_par_unico_en_ambos_sentidos(self):
        Contacto.objects.create(jugador=self.a, contacto=self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contacto.objects.create(jugador=self.b, contacto=self.a)

    def test_par_unico_en_el_mismo_sentido(self):
        Contacto.objects.create(jugador=self.a, contacto=self.b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contacto.objects.create(jugador=self.a, contacto=self.b)


class InvitacionTests(SocialBaseTestCase):
    def invitar(self, lobby=None, emisor=None, receptor=None):
        return Invitacion(
            lobby=lobby or self.privado,
            emisor=emisor or self.capitan,
            receptor=receptor or self.otro,
        )

    def test_crea_pendiente_y_str(self):
        invitacion = self.invitar()
        invitacion.save()
        self.assertEqual(invitacion.estado, Invitacion.Estado.PENDIENTE)
        self.assertIn("Invitación", str(invitacion))

    def test_jugador_a_inscribir_es_el_receptor(self):
        self.assertEqual(self.invitar().jugador_a_inscribir, self.otro)

    def test_solo_un_inscripto_puede_invitar(self):
        with self.assertRaises(ValidationError) as ctx:
            self.invitar(emisor=self.jugador("intruso")).save()
        self.assertIn("emisor", ctx.exception.message_dict)

    def test_receptor_ya_inscripto(self):
        self.privado.inscribir(self.otro)
        with self.assertRaises(ValidationError) as ctx:
            self.invitar().save()
        self.assertIn("receptor", ctx.exception.message_dict)

    def test_lobby_que_no_esta_en_formacion(self):
        self.privado.cancelar()
        with self.assertRaises(ValidationError):
            self.invitar().save()

    def test_no_puede_invitarse_a_si_mismo(self):
        with self.assertRaises(ValidationError):
            self.invitar(receptor=self.capitan).save()

    def test_invitacion_pendiente_unica_por_receptor(self):
        self.invitar().save()
        with self.assertRaises(ValidationError):
            Invitacion.objects.create(lobby=self.privado, emisor=self.capitan, receptor=self.otro)

    def test_rechazada_permite_invitar_de_nuevo(self):
        primera = self.invitar()
        primera.save()
        primera.rechazar()
        self.invitar().save()

    def test_aceptar_inscribe_al_receptor(self):
        invitacion = self.invitar()
        invitacion.save()
        invitacion.aceptar()
        self.assertEqual(invitacion.estado, Invitacion.Estado.ACEPTADA)
        self.assertTrue(self.privado.inscripciones.filter(jugador=self.otro).exists())

    def test_rechazar_no_inscribe(self):
        invitacion = self.invitar()
        invitacion.save()
        invitacion.rechazar()
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.RECHAZADA)
        self.assertFalse(self.privado.inscripciones.filter(jugador=self.otro).exists())

    def test_no_se_responde_dos_veces(self):
        invitacion = self.invitar()
        invitacion.save()
        invitacion.rechazar()
        with self.assertRaises(Conflicto):
            invitacion.aceptar()
        with self.assertRaises(Conflicto):
            invitacion.rechazar()

    def test_aceptar_sin_cupo_revierte_el_cambio_de_estado(self):
        invitacion = self.invitar()
        invitacion.save()
        self.llenar(self.privado)
        Invitacion.objects.filter(pk=invitacion.pk).update(estado=Invitacion.Estado.PENDIENTE)
        with self.assertRaises(Conflicto):
            invitacion.aceptar()
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.PENDIENTE)

    def test_las_validaciones_no_se_repiten_al_cambiar_de_estado(self):
        invitacion = self.invitar()
        invitacion.save()
        self.privado.cancelar()
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.EXPIRADA)
        invitacion.estado = Invitacion.Estado.RECHAZADA
        invitacion.save()


class SolicitudAccesoTests(SocialBaseTestCase):
    def solicitar(self, lobby=None, jugador=None):
        return SolicitudAcceso(lobby=lobby or self.privado, jugador=jugador or self.otro)

    def test_crea_pendiente_y_str(self):
        solicitud = self.solicitar()
        solicitud.save()
        self.assertEqual(solicitud.estado, SolicitudAcceso.Estado.PENDIENTE)
        self.assertIn("Solicitud", str(solicitud))

    def test_jugador_a_inscribir_es_el_solicitante(self):
        self.assertEqual(self.solicitar().jugador_a_inscribir, self.otro)

    def test_lobby_publico_no_admite_solicitudes(self):
        with self.assertRaises(ValidationError):
            self.solicitar(lobby=self.publico).save()

    def test_jugador_ya_inscripto(self):
        with self.assertRaises(ValidationError) as ctx:
            self.solicitar(jugador=self.capitan).save()
        self.assertIn("jugador", ctx.exception.message_dict)

    def test_lobby_que_no_esta_en_formacion(self):
        self.privado.cancelar()
        with self.assertRaises(ValidationError):
            self.solicitar().save()

    def test_solicitud_pendiente_unica(self):
        self.solicitar().save()
        with self.assertRaises(ValidationError):
            SolicitudAcceso.objects.create(lobby=self.privado, jugador=self.otro)

    def test_aceptar_inscribe_al_solicitante(self):
        solicitud = self.solicitar()
        solicitud.save()
        solicitud.aceptar()
        self.assertEqual(solicitud.estado, SolicitudAcceso.Estado.ACEPTADA)
        self.assertTrue(self.privado.inscripciones.filter(jugador=self.otro).exists())

    def test_rechazar(self):
        solicitud = self.solicitar()
        solicitud.save()
        solicitud.rechazar()
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.estado, SolicitudAcceso.Estado.RECHAZADA)

    def test_no_se_responde_dos_veces(self):
        solicitud = self.solicitar()
        solicitud.save()
        solicitud.aceptar()
        with self.assertRaises(Conflicto):
            solicitud.rechazar()

    def test_turno_del_lobby_sigue_bloqueado_tras_aceptar(self):
        solicitud = self.solicitar()
        solicitud.save()
        solicitud.aceptar()
        self.privado.turno.refresh_from_db()
        self.assertEqual(self.privado.turno.estado, Turno.Estado.BLOQUEADO)
