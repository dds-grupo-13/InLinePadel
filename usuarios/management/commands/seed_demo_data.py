from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from clubes.models import Cancha, Club, Turno
from partidas.models import Inscripcion, Lobby, Reserva
from social.models import Invitacion, SolicitudAcceso
from usuarios.models import AdminSistema, Jugador, Usuario


class Command(BaseCommand):
    help = 'Seeds realistic demo data to showcase the app for the PO.'

    def handle(self, *args, **options):
        self.stdout.write('Generating demo data...')

        demo_user, created = Usuario.objects.get_or_create(
            email='demo@inlinepadel.com',
            defaults={'is_active': True, 'is_staff': False},
        )
        if created or not demo_user.check_password('demo123'):
            demo_user.set_password('demo123')
            demo_user.save()

        demo_jugador, _ = Jugador.objects.get_or_create(
            usuario=demo_user,
            defaults={
                'nombre': 'María',
                'apellido': 'López',
                'posicion_preferida': Jugador.Posicion.DRIVE,
                'zona': 'Palermo',
                'puntaje': 1420,
                'partidos_registrados': 8,
            },
        )

        admin_user, _ = Usuario.objects.get_or_create(
            email='admin@inlinepadel.com',
            defaults={'is_active': True, 'is_staff': True},
        )
        if not admin_user.check_password('admin123'):
            admin_user.set_password('admin123')
            admin_user.save()
        admin_sistema, _ = AdminSistema.objects.get_or_create(usuario=admin_user)

        club_1, _ = Club.objects.get_or_create(
            denominacion='Club Padel Norte',
            defaults={
                'direccion': 'Av. Santa Fe 2560',
                'zona': 'Palermo',
                'estado': Club.Estado.ACTIVO,
                'habilitado_por': admin_sistema,
            },
        )
        club_2, _ = Club.objects.get_or_create(
            denominacion='Arena Padel Sur',
            defaults={
                'direccion': 'Calle Córdoba 1450',
                'zona': 'Villa Crespo',
                'estado': Club.Estado.ACTIVO,
                'habilitado_por': admin_sistema,
            },
        )
        Club.objects.get_or_create(
            denominacion='Club Demo Sin Canchas',
            defaults={
                'direccion': 'Av. Demo 999',
                'zona': 'Caballito',
                'estado': Club.Estado.ACTIVO,
                'habilitado_por': admin_sistema,
            },
        )

        cancha_1, _ = Cancha.objects.get_or_create(
            club=club_1,
            identificacion='Cancha A1',
            defaults={'tipo': Cancha.Tipo.TECHADA},
        )
        cancha_2, _ = Cancha.objects.get_or_create(
            club=club_1,
            identificacion='Cancha B2',
            defaults={'tipo': Cancha.Tipo.DESCUBIERTA},
        )
        cancha_3, _ = Cancha.objects.get_or_create(
            club=club_2,
            identificacion='Cancha 03',
            defaults={'tipo': Cancha.Tipo.TECHADA},
        )

        turno_1, _ = Turno.objects.get_or_create(
            cancha=cancha_1,
            fecha=timezone.now().date() + timedelta(days=1),
            hora_inicio='19:00:00',
            defaults={'duracion': 90, 'precio': 2100, 'estado': Turno.Estado.LIBRE},
        )
        turno_2, _ = Turno.objects.get_or_create(
            cancha=cancha_2,
            fecha=timezone.now().date() + timedelta(days=2),
            hora_inicio='21:00:00',
            defaults={'duracion': 90, 'precio': 2400, 'estado': Turno.Estado.BLOQUEADO},
        )
        turno_3, _ = Turno.objects.get_or_create(
            cancha=cancha_3,
            fecha=timezone.now().date() + timedelta(days=1),
            hora_inicio='18:30:00',
            defaults={'duracion': 90, 'precio': 2300, 'estado': Turno.Estado.CONFIRMADO},
        )

        captain_users = []
        for email, nombre, apellido, zona in [
            ('carlos@inlinepadel.com', 'Carlos', 'Rossi', 'Belgrano'),
            ('lucia@inlinepadel.com', 'Lucia', 'Fernández', 'Recoleta'),
            ('nicolas@inlinepadel.com', 'Nicolás', 'Molina', 'Colegiales'),
            ('sofia@inlinepadel.com', 'Sofía', 'Duarte', 'Villa Urquiza'),
        ]:
            user, _ = Usuario.objects.get_or_create(email=email, defaults={'is_active': True})
            if not user.check_password('demo123'):
                user.set_password('demo123')
                user.save()
            jugador, _ = Jugador.objects.get_or_create(
                usuario=user,
                defaults={'nombre': nombre, 'apellido': apellido, 'zona': zona, 'partidos_registrados': 4},
            )
            captain_users.append(jugador)

        lobby_1, _ = Lobby.objects.get_or_create(
            pk=1,
            defaults={
                'privacidad': Lobby.Privacidad.PUBLICO,
                'rango_min': 3,
                'rango_max': 5,
                'admite_provisorios': True,
                'plazo_limite': timezone.now() + timedelta(days=2),
                'estado': Lobby.Estado.EN_FORMACION,
            },
        )
        if lobby_1.pk == 1:
            for idx, jugador in enumerate(captain_users[:3], start=1):
                Inscripcion.objects.get_or_create(
                    lobby=lobby_1,
                    jugador=jugador,
                    defaults={'numero_cupo': idx, 'rol': Inscripcion.Rol.CAPITAN if idx == 1 else Inscripcion.Rol.JUGADOR},
                )

        Reserva.objects.get_or_create(
            lobby=lobby_1,
            defaults={
                'turno': turno_1,
                'estado': Reserva.Estado.PROVISORIA,
                'codigo_reserva': None,
            },
        )

        lobby_2, _ = Lobby.objects.get_or_create(
            pk=2,
            defaults={
                'privacidad': Lobby.Privacidad.SOLO_AMIGOS,
                'rango_min': 2,
                'rango_max': 5,
                'admite_provisorios': False,
                'plazo_limite': timezone.now() + timedelta(days=1),
                'estado': Lobby.Estado.COMPLETO,
            },
        )

        if lobby_2:
            for idx, jugador in enumerate(captain_users[1:4], start=1):
                Inscripcion.objects.get_or_create(
                    lobby=lobby_2,
                    jugador=jugador,
                    defaults={'numero_cupo': idx, 'rol': Inscripcion.Rol.CAPITAN if idx == 1 else Inscripcion.Rol.JUGADOR},
                )

        reserva, _ = Reserva.objects.get_or_create(
            lobby=lobby_2,
            defaults={
                'turno': turno_3,
                'estado': Reserva.Estado.CONFIRMADA,
                'codigo_reserva': 'RES-DEMO-001',
            },
        )

        if reserva and not reserva.turno_id:
            reserva.turno = turno_3
            reserva.save()

        if not hasattr(lobby_2, 'reserva') or lobby_2.reserva is None:
            Reserva.objects.get_or_create(
                lobby=lobby_2,
                turno=turno_3,
                defaults={'estado': Reserva.Estado.CONFIRMADA, 'codigo_reserva': 'RES-DEMO-001'},
            )

        turno_1.estado = Turno.Estado.BLOQUEADO
        turno_1.save(update_fields=['estado'])

        for lobby, jugador in [(lobby_1, demo_jugador), (lobby_2, captain_users[0])]:
            SolicitudAcceso.objects.get_or_create(
                lobby=lobby,
                jugador=jugador,
                defaults={'estado': SolicitudAcceso.Estado.PENDIENTE},
            )

        Invitacion.objects.get_or_create(
            lobby=lobby_1,
            jugador=demo_jugador,
            defaults={'emisor': captain_users[0], 'estado': Invitacion.Estado.PENDIENTE},
        )

        self.stdout.write(self.style.SUCCESS('Demo data ready.'))
