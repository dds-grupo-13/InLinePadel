from datetime import datetime, time, timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clubes.models import Cancha, Club, Turno, Zona
from partidas.models import Inscripcion, Lobby
from social.models import Contacto, Invitacion, Notificacion, SolicitudAcceso
from usuarios.models import Jugador, Usuario

PASSWORD_SUPER = "admin"
PASSWORD_ADMIN = "clubadmin123"
PASSWORD_JUGADOR = "demo1234"

CODIGO_CHECK_IN = "CAFE-2026"  # hexadecimal: la pantalla de check-in solo acepta 0-9 y A-F
CODIGO_JUGADO = "ACE0-0001"

HORAS_GRILLA = [time(10, 0), time(11, 30), time(16, 30), time(18, 0), time(19, 30), time(21, 0)]

ZONAS = ["Zarate", "Escobar", "Campana"]
CLUBES = [
    # (denominación, zona, dirección, admin, canchas [(número, tipo)], precio del turno)
    ("Club Padel Norte", "Zarate", "Av. Santa Fe 2560", "admin.norte@inlinepadel.com",
     [(1, Cancha.Tipo.TECHADA), (2, Cancha.Tipo.DESCUBIERTA)], 32000),
    ("Padel Central", "Campana", "Av. Corrientes 1234", "admin.norte@inlinepadel.com",
     [(1, Cancha.Tipo.TECHADA)], 28000),
    ("Arena Padel Sur", "Escobar", "Av. Rivadavia 8450", "admin.sur@inlinepadel.com",
     [(1, Cancha.Tipo.TECHADA), (2, Cancha.Tipo.DESCUBIERTA)], 30000),
]
JUGADORES = [
    # (username, nombre, apellido, posición, zona)
    ("demo@inlinepadel.com", "María", "López", Jugador.Posiciones.DRIVE, "Zarate"),
    ("carlos@inlinepadel.com", "Carlos", "Rossi", Jugador.Posiciones.REVES, "Zarate"),
    ("lucia@inlinepadel.com", "Lucía", "Fernández", Jugador.Posiciones.DRIVE, "Escobar"),
    ("nico@inlinepadel.com", "Nicolás", "Molina", Jugador.Posiciones.INDISTINTO, "Campana"),
    ("sofia@inlinepadel.com", "Sofía", "Duarte", Jugador.Posiciones.REVES, "Escobar"),
]


def _redondear(dt, minutos):
    dt = dt.replace(second=0, microsecond=0)
    resto = dt.minute % minutos
    return dt + timedelta(minutes=(minutos - resto) % minutos)


class Command(BaseCommand):
    help = "Reinicia los datos demo para presentar en vivo (ver el docstring del módulo)."

    @transaction.atomic
    def handle(self, *args, **options):
        self._limpiar()

        self._usuario("superAdmin@inLinePadel.com", PASSWORD_SUPER, is_staff=True,
                      is_superuser=True, first_name="Super", last_name="Admin")
        admins = {
            "admin.norte@inlinepadel.com": self._usuario(
                "admin.norte@inlinepadel.com", PASSWORD_ADMIN, is_staff=True,
                first_name="Ana", last_name="Norte"),
            "admin.sur@inlinepadel.com": self._usuario(
                "admin.sur@inlinepadel.com", PASSWORD_ADMIN, is_staff=True,
                first_name="Beto", last_name="Sur"),
        }
        zonas = {nombre: Zona.objects.get_or_create(nombre=nombre)[0] for nombre in ZONAS}

        canchas, precios = {}, {}
        for denominacion, zona, direccion, admin, lista, precio in CLUBES:
            club, _ = Club.objects.update_or_create(
                denominacion=denominacion,
                defaults={"zona": zonas[zona], "direccion": direccion,
                          "admin": admins[admin], "estado": Club.Estado.ACTIVO},
            )
            precios[denominacion] = precio
            for numero, tipo in lista:
                canchas[(denominacion, numero)], _ = Cancha.objects.update_or_create(
                    club=club, numero=numero, defaults={"tipo": tipo, "activa": True})

        # Recién ahora, con los clubes del seed reasignados, se pueden borrar las zonas
        # y los usuarios creados durante un ensayo.
        Zona.objects.exclude(nombre__in=ZONAS).delete()
        propios = ["superAdmin@inLinePadel.com", *admins, *[x[0] for x in JUGADORES]]
        Usuario.objects.exclude(username__in=propios).delete()

        j = {}
        for username, nombre, apellido, posicion, zona in JUGADORES:
            usuario = self._usuario(username, PASSWORD_JUGADOR, first_name=nombre,
                                    last_name=apellido)
            j[nombre], _ = Jugador.objects.update_or_create(
                usuario=usuario, defaults={"posicion": posicion, "zona": zonas[zona]})
        maria, carlos, lucia, nico, sofia = (j[n] for n in ("María", "Carlos", "Lucía", "Nicolás", "Sofía"))

        # Grilla de mañana y pasado en todas las canchas.
        hoy = timezone.localdate()
        for (denominacion, _), cancha in canchas.items():
            for dias in (1, 2):
                for hora in HORAS_GRILLA:
                    self._turno(cancha, hoy + timedelta(days=dias), hora, precios[denominacion])

        manana = hoy + timedelta(days=1)
        def turno(club, numero, hora):
            return Turno.objects.get(cancha=canchas[(club, numero)], fecha=manana, hora_inicio=hora)

        # Contactos.
        for a, b in ((maria, carlos), (maria, lucia), (maria, sofia), (carlos, lucia), (lucia, nico)):
            Contacto.objects.create(jugador=a, contacto=b, estado=Contacto.Estado.ACEPTADO)
        Contacto.objects.create(jugador=nico, contacto=maria)  # solicitud pendiente para María

        # Partidas de mañana.
        casi_completa = self._lobby(turno("Club Padel Norte", 2, time(21, 0)), carlos, [lucia, nico])
        de_maria = self._lobby(turno("Padel Central", 1, time(10, 0)), maria, [carlos])
        privada = self._lobby(turno("Arena Padel Sur", 1, time(19, 30)), lucia, [nico],
                              Lobby.Privacidad.PRIVADO)
        Invitacion.objects.create(lobby=privada, emisor=lucia, receptor=maria)
        completa = self._lobby(turno("Arena Padel Sur", 2, time(18, 0)), nico, [maria, carlos, lucia])

        # Partidas de hoy, relativas a la hora actual.
        ahora = timezone.localtime()
        inicio_check = _redondear(ahora + timedelta(minutes=10), 5)
        check_in = self._lobby(
            self._turno(canchas[("Club Padel Norte", 1)], inicio_check.date(),
                        inicio_check.time(), precios["Club Padel Norte"]),
            sofia, [nico, carlos, lucia])
        Lobby.objects.filter(pk=check_in.pk).update(codigo_reserva=CODIGO_CHECK_IN)

        inicio_firme = _redondear(ahora + timedelta(hours=2, minutes=30), 30)
        firme = self._lobby(
            self._turno(canchas[("Arena Padel Sur", 1)], inicio_firme.date(),
                        inicio_firme.time(), precios["Arena Padel Sur"]),
            lucia, [nico, carlos, maria])

        jugado = self._lobby_jugado(canchas[("Club Padel Norte", 2)], hoy - timedelta(days=1),
                                    [maria, carlos, lucia, nico])

        # Las notificaciones de armar los datos no aportan a la demo.
        Notificacion.objects.all().delete()
        cache.clear()  # reinicia el límite de intentos de login

        self._resumen(casi_completa, de_maria, privada, completa, check_in, firme, jugado)

    # ------------------------------------------------------------------ limpieza
    def _limpiar(self):
        Notificacion.objects.all().delete()
        Invitacion.objects.all().delete()
        SolicitudAcceso.objects.all().delete()
        Inscripcion.objects.all().delete()
        Lobby.objects.all().delete()
        Contacto.objects.all().delete()
        Turno.objects.all().delete()
        Cancha.objects.all().delete()
        Club.objects.exclude(denominacion__in=[c[0] for c in CLUBES]).delete()

    # ------------------------------------------------------------------ helpers
    def _usuario(self, username, password, **extra):
        usuario, _ = Usuario.objects.update_or_create(
            username=username,
            defaults={"email": username, "is_active": True, "is_staff": False,
                      "is_superuser": False, **extra},
        )
        usuario.set_password(password)
        usuario.save(update_fields=["password"])
        return usuario

    def _turno(self, cancha, fecha, hora, precio):
        turno = Turno(cancha=cancha, fecha=fecha, hora_inicio=hora, duracion=90, precio=precio)
        turno.save()
        return turno

    def _lobby(self, turno, capitan, otros, privacidad=Lobby.Privacidad.PUBLICO):
        lobby = Lobby.crear(turno, capitan, privacidad=privacidad)
        for jugador in otros:
            lobby.inscribir(jugador)
        lobby.refresh_from_db()
        return lobby

    def _lobby_jugado(self, cancha, fecha, jugadores):
        turno = Turno(cancha=cancha, fecha=fecha, hora_inicio=time(20, 0), duracion=90,
                      precio=30000, estado=Turno.Estado.CUMPLIDO)
        turno.save()
        lobby = Lobby(turno=turno, capitan=jugadores[0], estado=Lobby.Estado.JUGADO,
                      plazo_limite=turno.inicio - timedelta(hours=3),
                      fecha_check_in=turno.inicio, codigo_reserva=CODIGO_JUGADO)
        lobby.full_clean()
        lobby.save()
        for cupo, jugador in enumerate(jugadores, start=1):
            Inscripcion.objects.create(lobby=lobby, jugador=jugador, numero_cupo=cupo)
        return lobby

    def _resumen(self, casi, de_maria, privada, completa, check_in, firme, jugado):
        def cuando(l):
            return f"{timezone.localtime(l.turno.inicio):%d/%m %H:%M}"

        w = self.stdout.write
        w(self.style.SUCCESS("Datos demo listos."))
        w("")
        w("Usuarios")
        w(f"  Admin del sistema    superAdmin@inLinePadel.com / {PASSWORD_SUPER}")
        w(f"  Admin Norte/Central  admin.norte@inlinepadel.com / {PASSWORD_ADMIN}")
        w(f"  Admin Arena Sur      admin.sur@inlinepadel.com / {PASSWORD_ADMIN}")
        w(f"  Jugadores            demo@ (María), carlos@, lucia@, nico@, sofia@inlinepadel.com / {PASSWORD_JUGADOR}")
        w("")
        w("Partidas")
        w(f"  {cuando(casi)}  Club Padel Norte c2   3/4 pública (Carlos)    -> Sofía se une y se confirma")
        w(f"  {cuando(de_maria)}  Padel Central c1      2/4 pública (María)     -> límite de 2 como capitana")
        w(f"  {cuando(privada)}  Arena Padel Sur c1    2/4 PRIVADA (Lucía)     -> invitación pendiente para María")
        w(f"  {cuando(completa)}  Arena Padel Sur c2    4/4 (Nico)              -> María se baja; el club cancela")
        w(f"  {cuando(firme)}  Arena Padel Sur c1    4/4 FIRME (Lucía)       -> María cede el lugar a Sofía")
        w(f"  {cuando(check_in)}  Club Padel Norte c1   4/4 código {CODIGO_CHECK_IN}   -> check-in de admin.norte")
        w(f"  {cuando(jugado)}  Club Padel Norte c2   jugada, código {CODIGO_JUGADO} -> historial")
        w("")
        w("Contactos: María con Carlos, Lucía y Sofía; Carlos-Lucía; Lucía-Nico. "
          "Nico le envió una solicitud a María.")
        w(self.style.WARNING(
            f"El check-in con {CODIGO_CHECK_IN} sirve hasta las "
            f"{timezone.localtime(check_in.turno.fin):%H:%M} y la reserva firme hasta las "
            f"{timezone.localtime(firme.turno.inicio):%H:%M}. Para ensayar de nuevo, volvé a correr el comando."))
