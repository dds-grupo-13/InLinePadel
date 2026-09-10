from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clubes.models import Club, Cancha, Turno
from social.models import SolicitudAcceso
from usuarios.models import AdminSistema, Jugador, Usuario

from .models import Inscripcion, Lobby, Reserva


class AceptarSolicitudViewTests(TestCase):
    def setUp(self):
        self.capitan_user = Usuario.objects.create_user(email='capitan@example.com', password='secret123')
        self.capitan = Jugador.objects.create(
            usuario=self.capitan_user,
            nombre='Capitán',
            apellido='Principal',
            zona='Centro',
        )

        self.solicitante_user = Usuario.objects.create_user(email='solicitante@example.com', password='secret123')
        self.solicitante = Jugador.objects.create(
            usuario=self.solicitante_user,
            nombre='Jugador',
            apellido='Solicitante',
            zona='Norte',
        )

        self.lobby = Lobby.objects.create(
            privacidad=Lobby.Privacidad.PUBLICO,
            plazo_limite=timezone.now() + timedelta(days=1),
        )
        Inscripcion.objects.create(
            lobby=self.lobby,
            jugador=self.capitan,
            numero_cupo=1,
            rol=Inscripcion.Rol.CAPITAN,
        )
        self.solicitud = SolicitudAcceso.objects.create(
            lobby=self.lobby,
            jugador=self.solicitante,
            estado=SolicitudAcceso.Estado.PENDIENTE,
        )

    def test_capitan_puede_aceptar_solicitud(self):
        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('partidas:aceptar_solicitud', kwargs={'pk': self.solicitud.pk}),
            follow=True,
        )

        self.solicitud.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.solicitud.estado, SolicitudAcceso.Estado.ACEPTADA)
        self.assertTrue(
            Inscripcion.objects.filter(
                lobby=self.lobby,
                jugador=self.solicitante,
            ).exists()
        )


class InscripcionCreateViewTests(TestCase):
    def setUp(self):
        self.user = Usuario.objects.create_user(email='jugador@example.com', password='secret123')
        self.jugador = Jugador.objects.create(
            usuario=self.user,
            nombre='Jugador',
            apellido='Demo',
            zona='Centro',
        )
        self.lobby = Lobby.objects.create(
            privacidad=Lobby.Privacidad.PUBLICO,
            plazo_limite=timezone.now() + timedelta(days=1),
        )
        admin = Usuario.objects.create_user(email='admin@example.com', password='secret123')
        club = Club.objects.create(
            denominacion='Club Test',
            direccion='Calle Falsa 123',
            zona='Centro',
            habilitado_por=AdminSistema.objects.create(usuario=admin),
        )
        cancha = Cancha.objects.create(
            club=club,
            identificacion='Cancha 1',
            tipo=Cancha.Tipo.TECHADA,
        )
        turno = Turno.objects.create(
            cancha=cancha,
            fecha=timezone.now().date() + timedelta(days=1),
            hora_inicio=(timezone.now() + timedelta(hours=1)).time(),
            precio=100.00,
            estado=Turno.Estado.LIBRE,
        )
        self.reserva = Reserva.objects.create(
            lobby=self.lobby,
            turno=turno,
            estado=Reserva.Estado.PROVISORIA,
            codigo_reserva=None,
        )

    def test_unirse_lobby_solo_acepta_post(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('partidas:unirse_lobby', kwargs={'lobby_id': self.lobby.pk}))

        self.assertEqual(response.status_code, 405)


class ReservaCancelViewTests(TestCase):
    def setUp(self):
        # Crear admin del sistema
        self.admin_user = Usuario.objects.create_user(email='admin@example.com', password='secret123')
        self.admin_sistema = AdminSistema.objects.create(usuario=self.admin_user)

        # Crear club y cancha
        self.club = Club.objects.create(
            denominacion='Club de Padel Test',
            direccion='Calle Principal 123',
            zona='Centro',
            habilitado_por=self.admin_sistema,
        )
        self.cancha = Cancha.objects.create(
            club=self.club,
            identificacion='Cancha 1',
            tipo=Cancha.Tipo.TECHADA,
        )

        # Crear turno
        self.turno = Turno.objects.create(
            cancha=self.cancha,
            fecha=timezone.now().date(),
            hora_inicio=timezone.now().time(),
            precio=100.00,
            estado=Turno.Estado.CONFIRMADO,
        )

        # Crear capitán
        self.capitan_user = Usuario.objects.create_user(email='capitan@example.com', password='secret123')
        self.capitan = Jugador.objects.create(
            usuario=self.capitan_user,
            nombre='Capitán',
            apellido='Principal',
            zona='Centro',
        )

        # Crear lobby y reserva
        self.lobby = Lobby.objects.create(
            privacidad=Lobby.Privacidad.PUBLICO,
            plazo_limite=timezone.now() + timedelta(days=1),
        )
        self.reserva = Reserva.objects.create(
            lobby=self.lobby,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            codigo_reserva='RES-ABC123DEF456',
        )
        Inscripcion.objects.create(
            lobby=self.lobby,
            jugador=self.capitan,
            numero_cupo=1,
            rol=Inscripcion.Rol.CAPITAN,
        )

    def test_capitan_puede_cancelar_reserva(self):
        """El capitán puede cancelar su propia reserva."""
        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('partidas:cancelar_reserva', kwargs={'pk': self.reserva.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        # Validar que la reserva está cancelada
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.estado, Reserva.Estado.CANCELADA)

        # Validar que el lobby está cancelado
        self.lobby.refresh_from_db()
        self.assertEqual(self.lobby.estado, Lobby.Estado.CANCELADO)

        # Validar que el turno está libre
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.LIBRE)

    def test_no_capitan_no_puede_cancelar_reserva(self):
        """Un jugador que no es capitán no puede cancelar la reserva (BOLA prevention)."""
        otro_user = Usuario.objects.create_user(email='otro@example.com', password='secret123')
        otro_jugador = Jugador.objects.create(
            usuario=otro_user,
            nombre='Otro',
            apellido='Jugador',
            zona='Norte',
        )
        Inscripcion.objects.create(
            lobby=self.lobby,
            jugador=otro_jugador,
            numero_cupo=2,
            rol=Inscripcion.Rol.JUGADOR,
        )

        self.client.force_login(otro_user)

        response = self.client.get(
            reverse('partidas:cancelar_reserva', kwargs={'pk': self.reserva.pk}),
        )

        # Debe retornar 404 (no encontrado) porque el usuario no es el capitán
        self.assertEqual(response.status_code, 404)

        # La reserva no debe estar cancelada
        self.reserva.refresh_from_db()
        self.assertEqual(self.reserva.estado, Reserva.Estado.CONFIRMADA)

    def test_usuario_no_autenticado_redirige_a_login(self):
        """Un usuario no autenticado es redirigido a la página de login."""
        response = self.client.get(
            reverse('partidas:cancelar_reserva', kwargs={'pk': self.reserva.pk}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


class ReservaCheckInViewTests(TestCase):
    def setUp(self):
        self.admin_user = Usuario.objects.create_user(email='admin_checkin@example.com', password='secret123')
        self.admin_sistema = AdminSistema.objects.create(usuario=self.admin_user)
        self.club = Club.objects.create(
            denominacion='Club Check-In',
            direccion='Calle Check 123',
            zona='Centro',
            habilitado_por=self.admin_sistema,
        )
        self.cancha = Cancha.objects.create(
            club=self.club,
            identificacion='Cancha A',
            tipo=Cancha.Tipo.TECHADA,
        )
        self.turno = Turno.objects.create(
            cancha=self.cancha,
            fecha=timezone.now().date(),
            hora_inicio=timezone.now().time(),
            precio=100.00,
            estado=Turno.Estado.CONFIRMADO,
        )
        self.capitan_user = Usuario.objects.create_user(email='capitan_checkin@example.com', password='secret123')
        self.capitan = Jugador.objects.create(
            usuario=self.capitan_user,
            nombre='Capitán',
            apellido='CheckIn',
            zona='Sur',
        )
        self.lobby = Lobby.objects.create(
            privacidad=Lobby.Privacidad.PUBLICO,
            plazo_limite=timezone.now() + timedelta(days=1),
        )
        self.reserva = Reserva.objects.create(
            lobby=self.lobby,
            turno=self.turno,
            estado=Reserva.Estado.CONFIRMADA,
            codigo_reserva='RES-CHECK-001',
        )
        Inscripcion.objects.create(
            lobby=self.lobby,
            jugador=self.capitan,
            numero_cupo=1,
            rol=Inscripcion.Rol.CAPITAN,
        )

    def test_capitan_puede_hacer_check_in_de_reserva_confirmada(self):
        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('partidas:reserva_checkin', kwargs={'pk': self.reserva.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)

        self.reserva.refresh_from_db()
        self.turno.refresh_from_db()
        self.lobby.refresh_from_db()
        self.assertEqual(self.reserva.estado, Reserva.Estado.CUMPLIDA)
        self.assertIsNotNone(self.reserva.fecha_check_in)
        self.assertEqual(self.turno.estado, Turno.Estado.CUMPLIDO)
        self.assertEqual(self.lobby.estado, Lobby.Estado.JUGADO)

    def test_reserva_no_confirmada_no_puede_hacer_check_in(self):
        lobby_provisoria = Lobby.objects.create(
            privacidad=Lobby.Privacidad.PUBLICO,
            plazo_limite=timezone.now() + timedelta(days=2),
        )
        reserva_provisoria = Reserva.objects.create(
            lobby=lobby_provisoria,
            turno=Turno.objects.create(
                cancha=self.cancha,
                fecha=timezone.now().date() + timedelta(days=1),
                hora_inicio=(timezone.now() + timedelta(hours=2)).time(),
                precio=120.00,
                estado=Turno.Estado.BLOQUEADO,
            ),
            estado=Reserva.Estado.PROVISORIA,
            codigo_reserva='RES-PROV-1',
        )
        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('partidas:reserva_checkin', kwargs={'pk': reserva_provisoria.pk}),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        reserva_provisoria.refresh_from_db()
        self.assertEqual(reserva_provisoria.estado, Reserva.Estado.PROVISORIA)
        self.assertIsNone(reserva_provisoria.fecha_check_in)

    def test_usuario_no_autenticado_redirige_a_login(self):
        response = self.client.get(
            reverse('partidas:reserva_checkin', kwargs={'pk': self.reserva.pk}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
