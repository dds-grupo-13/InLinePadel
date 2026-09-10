from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from partidas.models import Inscripcion, Lobby
from usuarios.models import Jugador, Usuario

from .models import Invitacion


class InvitacionCreateViewTests(TestCase):
    def setUp(self):
        self.capitan_user = Usuario.objects.create_user(email='capitan@example.com', password='secret123')
        self.capitan = Jugador.objects.create(
            usuario=self.capitan_user,
            nombre='Capitán',
            apellido='Principal',
            zona='Centro',
        )

        self.jugador_invitar_user = Usuario.objects.create_user(email='invitar@example.com', password='secret123')
        self.jugador_invitar = Jugador.objects.create(
            usuario=self.jugador_invitar_user,
            nombre='Jugador',
            apellido='Invitable',
            zona='Norte',
        )

        self.otro_jugador_user = Usuario.objects.create_user(email='otro@example.com', password='secret123')
        self.otro_jugador = Jugador.objects.create(
            usuario=self.otro_jugador_user,
            nombre='Otro',
            apellido='Jugador',
            zona='Sur',
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

    def test_capitan_puede_enviar_invitacion(self):
        """El capitán del lobby puede enviar una invitación a un jugador."""
        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('social:crear_invitacion', kwargs={'lobby_id': self.lobby.pk}),
            {'jugador': self.jugador_invitar.pk},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            Invitacion.objects.filter(
                lobby=self.lobby,
                jugador=self.jugador_invitar,
                estado=Invitacion.Estado.PENDIENTE,
            ).exists()
        )

    def test_no_capitan_no_puede_enviar_invitacion(self):
        """Un jugador que no es capitán no puede enviar invitaciones."""
        self.client.force_login(self.jugador_invitar_user)

        response = self.client.post(
            reverse('social:crear_invitacion', kwargs={'lobby_id': self.lobby.pk}),
            {'jugador': self.otro_jugador.pk},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Invitacion.objects.filter(
                lobby=self.lobby,
                jugador=self.otro_jugador,
            ).exists()
        )

    def test_no_puede_invitar_jugador_ya_inscripto(self):
        """No se puede invitar a un jugador que ya está inscripto en el lobby."""
        Inscripcion.objects.create(
            lobby=self.lobby,
            jugador=self.jugador_invitar,
            numero_cupo=2,
            rol=Inscripcion.Rol.JUGADOR,
        )

        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('social:crear_invitacion', kwargs={'lobby_id': self.lobby.pk}),
            {'jugador': self.jugador_invitar.pk},
        )

        # Valida que haya un error y que no se haya creado otra invitación
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Invitacion.objects.filter(
                lobby=self.lobby,
                jugador=self.jugador_invitar,
            ).count(),
            0,
        )

    def test_no_puede_invitar_con_invitacion_pendiente(self):
        """No se puede invitar a un jugador que ya tiene una invitación pendiente."""
        Invitacion.objects.create(
            lobby=self.lobby,
            jugador=self.jugador_invitar,
            emisor=self.capitan,
            estado=Invitacion.Estado.PENDIENTE,
        )

        self.client.force_login(self.capitan_user)

        response = self.client.post(
            reverse('social:crear_invitacion', kwargs={'lobby_id': self.lobby.pk}),
            {'jugador': self.jugador_invitar.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Invitacion.objects.filter(
                lobby=self.lobby,
                jugador=self.jugador_invitar,
                estado=Invitacion.Estado.PENDIENTE,
            ).count(),
            1,
        )
