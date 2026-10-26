from datetime import time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clubes.models import Cancha, Club, Turno, Zona
from config.exceptions import Conflicto, ErrorDominio
from partidas.models import Inscripcion, Lobby
from social.models import Contacto, Invitacion, SolicitudAcceso
from usuarios.models import Jugador, Usuario

PASSWORD_SUPER = "admin"
PASSWORD_ADMIN = "clubadmin123"
PASSWORD_JUGADOR = "demo1234"

CODIGO_CHECK_IN = "CHK-DEMO"
CODIGO_JUGADO = "PLAY-001"

HORAS = [time(10, 0), time(11, 30), time(16, 30), time(18, 0), time(19, 30), time(21, 0)]


class Command(BaseCommand):
    help = (
        "Carga datos demo (usuarios, clubes, turnos, partidas y pedidos) "
        "para la presentación. Es idempotente."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Generando datos demo...")

        self._limpiar_lobbies_vencidos()

        superadmin = self._usuario(
            "superAdmin@inLinePadel.com",
            PASSWORD_SUPER,
            is_staff=True,
            is_superuser=True,
            first_name="Super",
            last_name="Admin",
        )
        admin_norte = self._usuario(
            "admin.norte@inlinepadel.com",
            PASSWORD_ADMIN,
            is_staff=True,
            first_name="Ana",
            last_name="Norte",
        )
        admin_sur = self._usuario(
            "admin.sur@inlinepadel.com",
            PASSWORD_ADMIN,
            is_staff=True,
            first_name="Beto",
            last_name="Sur",
        )

        zona_norte = self._zona("Norte")
        zona_sur = self._zona("Sur")
        zona_centro = self._zona("Centro")

        club_norte = self._club(
            zona_norte, "Club Padel Norte", "Av. Santa Fe 2560", admin_norte
        )
        club_sur = self._club(
            zona_sur, "Arena Padel Sur", "Av. Rivadavia 8450", admin_sur
        )
        club_centro = self._club(
            zona_centro, "Padel Central", "Av. Corrientes 1234", admin_norte
        )

        norte_1 = self._cancha(club_norte, 1, Cancha.Tipo.TECHADA)
        norte_2 = self._cancha(club_norte, 2, Cancha.Tipo.DESCUBIERTA)
        sur_1 = self._cancha(club_sur, 1, Cancha.Tipo.TECHADA)
        sur_2 = self._cancha(club_sur, 2, Cancha.Tipo.DESCUBIERTA)
        centro_1 = self._cancha(club_centro, 1, Cancha.Tipo.TECHADA)

        jugadores = {}
        for username, nombre, apellido, posicion, zona in [
            ("demo@inlinepadel.com", "María", "López", Jugador.Posiciones.DRIVE, zona_norte),
            ("carlos@inlinepadel.com", "Carlos", "Rossi", Jugador.Posiciones.REVES, zona_norte),
            ("lucia@inlinepadel.com", "Lucía", "Fernández", Jugador.Posiciones.DRIVE, zona_sur),
            ("nico@inlinepadel.com", "Nicolás", "Molina", Jugador.Posiciones.INDISTINTO, zona_centro),
            ("sofia@inlinepadel.com", "Sofía", "Duarte", Jugador.Posiciones.REVES, zona_sur),
        ]:
            usuario = self._usuario(
                username, PASSWORD_JUGADOR, first_name=nombre, last_name=apellido
            )
            jugadores[username] = self._jugador(usuario, zona, posicion)

        maria = jugadores["demo@inlinepadel.com"]
        carlos = jugadores["carlos@inlinepadel.com"]
        lucia = jugadores["lucia@inlinepadel.com"]
        nico = jugadores["nico@inlinepadel.com"]
        sofia = jugadores["sofia@inlinepadel.com"]

        manana = timezone.localdate() + timedelta(days=1)

        for cancha in (norte_1, norte_2, sur_1, sur_2, centro_1):
            for hora in HORAS:
                self._turno(cancha, manana, hora, 2000 + hora.hour * 50)

        for offset in (3, 5):
            fecha = timezone.localdate() + timedelta(days=offset)
            for cancha in (norte_1, sur_1, centro_1):
                for hora in (time(18, 0), time(20, 0)):
                    self._turno(cancha, fecha, hora, 2300 + hora.hour * 50)

        turno_a = self._turno(norte_1, manana, time(16, 30), 2200)
        turno_b = self._turno(norte_2, manana, time(18, 0), 2300)
        turno_c = self._turno(sur_1, manana, time(19, 30), 2400)
        turno_d = self._turno(norte_1, manana, time(21, 0), 2500)

        lobby_a = self._lobby(turno_a, maria, [carlos])
        lobby_b = self._lobby(turno_b, lucia, [nico, sofia])
        lobby_c = self._lobby(turno_c, carlos, [maria], privacidad=Lobby.Privacidad.PRIVADO)
        lobby_d = self._lobby(turno_d, nico, [maria, carlos, lucia])

        lobby_check_in = self._lobby_check_in(sofia, maria, carlos, nico)
        lobby_jugado = self._lobby_jugado(maria, carlos, lucia, nico)

        self._contacto(maria, carlos, Contacto.Estado.ACEPTADO)
        self._contacto(carlos, lucia, Contacto.Estado.ACEPTADO)
        self._contacto(sofia, lucia, Contacto.Estado.PENDIENTE)

        if (
            lobby_a is not None
            and lobby_a.estado == Lobby.Estado.EN_FORMACION
            and not lobby_a.inscripciones.filter(jugador=sofia).exists()
            and not Invitacion.objects.filter(
                lobby=lobby_a, receptor=sofia, estado=Invitacion.Estado.PENDIENTE
            ).exists()
        ):
            Invitacion.objects.create(lobby=lobby_a, emisor=maria, receptor=sofia)

        if (
            lobby_c is not None
            and lobby_c.estado == Lobby.Estado.EN_FORMACION
            and not lobby_c.inscripciones.filter(jugador=sofia).exists()
            and not SolicitudAcceso.objects.filter(
                lobby=lobby_c, jugador=sofia, estado=SolicitudAcceso.Estado.PENDIENTE
            ).exists()
        ):
            SolicitudAcceso.objects.create(lobby=lobby_c, jugador=sofia)

        self.stdout.write(self.style.SUCCESS("Datos demo listos."))
        self.stdout.write("")
        self.stdout.write("Credenciales:")
        self.stdout.write(f"  Superusuario      superAdmin@inLinePadel.com / {PASSWORD_SUPER}")
        self.stdout.write(f"  Admin Club Norte  admin.norte@inlinepadel.com / {PASSWORD_ADMIN}")
        self.stdout.write(f"  Admin Arena Sur   admin.sur@inlinepadel.com / {PASSWORD_ADMIN}")
        for username in jugadores:
            self.stdout.write(f"  Jugador           {username} / {PASSWORD_JUGADOR}")
        self.stdout.write("")
        self.stdout.write("Códigos para probar:")
        self.stdout.write(f"  Check-in inmediato  {CODIGO_CHECK_IN} (lobby {lobby_check_in.pk}, Arena Padel Sur)")
        if lobby_d is not None and lobby_d.codigo_reserva:
            self.stdout.write(
                f"  Reserva completa    {lobby_d.codigo_reserva} "
                f"(lobby {lobby_d.pk}, {lobby_d.turno.fecha:%d/%m} "
                f"{lobby_d.turno.hora_inicio:%H:%M})"
            )
        self.stdout.write(f"  Historial jugado    {CODIGO_JUGADO} (lobby {lobby_jugado.pk})")
        self.stdout.write("")
        self.stdout.write(
            "El check-in con CHK-DEMO funciona ya porque el turno es pasado; "
            "para repetirlo, volvé a correr este comando."
        )
        if superadmin is None:
            self.stdout.write(self.style.WARNING("No se pudo crear el superusuario."))

    def _limpiar_lobbies_vencidos(self):
        vencidos = Lobby.objects.filter(
            estado=Lobby.Estado.EN_FORMACION,
            turno__inicio__lt=timezone.now(),
        )
        cancelados = 0
        for lobby in vencidos:
            try:
                lobby._cancelar(Lobby.CanceladaPor.SISTEMA)
                cancelados += 1
            except (ErrorDominio, Conflicto):
                pass
        if cancelados:
            self.stdout.write(
                f"Se cancelaron {cancelados} partidas vencidas de corridas anteriores."
            )

    def _usuario(self, username, password, **extra):
        usuario, creado = Usuario.objects.get_or_create(
            username=username,
            defaults={"email": username, **extra},
        )
        campos = []
        if usuario.email != username:
            usuario.email = username
            campos.append("email")
        for campo, valor in extra.items():
            if getattr(usuario, campo) != valor:
                setattr(usuario, campo, valor)
                campos.append(campo)
        if creado or not usuario.check_password(password):
            usuario.set_password(password)
            campos.append("password")
        if campos:
            usuario.save(update_fields=campos)
        return usuario

    def _zona(self, nombre):
        zona, _ = Zona.objects.get_or_create(nombre=nombre)
        return zona

    def _club(self, zona, denominacion, direccion, admin):
        club, _ = Club.objects.get_or_create(
            zona=zona,
            denominacion=denominacion,
            defaults={"direccion": direccion, "admin": admin, "estado": Club.Estado.ACTIVO},
        )
        club.direccion = direccion
        club.admin = admin
        club.estado = Club.Estado.ACTIVO
        club.full_clean()
        club.save()
        return club

    def _cancha(self, club, numero, tipo):
        cancha, _ = Cancha.objects.get_or_create(
            club=club,
            numero=numero,
            defaults={"tipo": tipo, "activa": True},
        )
        cancha.tipo = tipo
        cancha.activa = True
        cancha.full_clean()
        cancha.save()
        return cancha

    def _turno(self, cancha, fecha, hora, precio, estado=Turno.Estado.LIBRE):
        turno = Turno.objects.filter(
            cancha=cancha, fecha=fecha, hora_inicio=hora
        ).first()
        if turno is None:
            turno = Turno(
                cancha=cancha,
                fecha=fecha,
                hora_inicio=hora,
                duracion=90,
                precio=precio,
                estado=estado,
            )
            turno.save()
        return turno

    def _jugador(self, usuario, zona, posicion):
        jugador, _ = Jugador.objects.get_or_create(
            usuario=usuario,
            defaults={"zona": zona, "posicion": posicion},
        )
        jugador.zona = zona
        jugador.posicion = posicion
        jugador.save(update_fields=["zona", "posicion"])
        return jugador

    def _lobby(self, turno, capitan, jugadores, privacidad=Lobby.Privacidad.PUBLICO):
        existente = (
            Lobby.objects.filter(turno=turno)
            .exclude(estado=Lobby.Estado.CANCELADO)
            .first()
        )
        if existente is None:
            try:
                existente = Lobby.crear(turno, capitan, privacidad=privacidad)
            except (ErrorDominio, Conflicto) as exc:
                self.stdout.write(
                    self.style.WARNING(f"No se pudo crear el lobby de {turno}: {exc}")
                )
                return None
        for jugador in jugadores:
            if existente.inscripciones.filter(jugador=jugador).exists():
                continue
            if existente.estado != Lobby.Estado.EN_FORMACION:
                break
            try:
                existente.inscribir(jugador)
            except (ErrorDominio, Conflicto) as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"No se pudo inscribir a {jugador} en el lobby {existente.pk}: {exc}"
                    )
                )
        existente.refresh_from_db(fields=["estado", "codigo_reserva"])
        return existente

    def _lobby_check_in(self, *jugadores):
        lobby = Lobby.objects.filter(codigo_reserva=CODIGO_CHECK_IN).first()
        if lobby is None:
            turno = self._turno(
                Cancha.objects.get(club__denominacion="Arena Padel Sur", numero=2),
                timezone.localdate() - timedelta(days=1),
                time(22, 30),
                2400,
                Turno.Estado.CONFIRMADO,
            )
            lobby = self._crear_lobby_pasado(
                turno,
                jugadores[0],
                Lobby.Estado.COMPLETO,
                CODIGO_CHECK_IN,
                Lobby.Privacidad.PRIVADO,
            )
        else:
            Lobby.objects.filter(pk=lobby.pk).update(
                estado=Lobby.Estado.COMPLETO, codigo_reserva=CODIGO_CHECK_IN
            )
            Turno.objects.filter(pk=lobby.turno_id).update(estado=Turno.Estado.CONFIRMADO)
            lobby.inscripciones.all().delete()
            lobby.refresh_from_db(fields=["estado", "codigo_reserva"])
        self._inscribir_directo(lobby, list(jugadores))
        return lobby

    def _lobby_jugado(self, *jugadores):
        lobby = Lobby.objects.filter(codigo_reserva=CODIGO_JUGADO).first()
        if lobby is None:
            turno = self._turno(
                Cancha.objects.get(club__denominacion="Club Padel Norte", numero=1),
                timezone.localdate() - timedelta(days=1),
                time(18, 0),
                2100,
                Turno.Estado.CUMPLIDO,
            )
            lobby = self._crear_lobby_pasado(
                turno,
                jugadores[0],
                Lobby.Estado.JUGADO,
                CODIGO_JUGADO,
                Lobby.Privacidad.PUBLICO,
            )
        self._inscribir_directo(lobby, list(jugadores))
        return lobby

    def _crear_lobby_pasado(self, turno, capitan, estado, codigo, privacidad):
        lobby = Lobby(
            turno=turno,
            capitan=capitan,
            privacidad=privacidad,
            estado=estado,
            plazo_limite=turno.inicio - timedelta(hours=2),
            fecha_check_in=turno.inicio,
            codigo_reserva=codigo,
        )
        lobby.full_clean()
        lobby.save()
        return lobby

    def _inscribir_directo(self, lobby, jugadores):
        ocupados = set(
            lobby.inscripciones.values_list("numero_cupo", flat=True)
        )
        for jugador in jugadores:
            if lobby.inscripciones.filter(jugador=jugador).exists():
                continue
            libres = [
                n for n in range(1, Lobby.CANTIDAD_CUPOS + 1) if n not in ocupados
            ]
            if not libres:
                break
            Inscripcion.objects.create(
                lobby=lobby, jugador=jugador, numero_cupo=libres[0]
            )
            ocupados.add(libres[0])

    def _contacto(self, jugador, contacto, estado):
        contacto_obj, creado = Contacto.objects.get_or_create(
            jugador=jugador, contacto=contacto, defaults={"estado": estado}
        )
        if not creado and contacto_obj.estado != estado:
            contacto_obj.estado = estado
            contacto_obj.save(update_fields=["estado"])
        return contacto_obj
