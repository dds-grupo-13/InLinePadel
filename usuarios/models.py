from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone

from config.exceptions import Conflicto


class Usuario(AbstractUser):
    email = models.EmailField(unique=True)


class Jugador(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="jugador",
    )

    class Posiciones(models.TextChoices):
        REVES = "REVES", "Revés"
        DRIVE = "DRIVE", "Drive"
        INDISTINTO = "INDISTINTO", "Indistinto"

    posicion = models.CharField(
        max_length=10,
        choices=Posiciones.choices,
        default=Posiciones.INDISTINTO,
    )

    zona = models.ForeignKey(
        "clubes.Zona",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jugadores",
    )

    def dar_de_baja(self):
        from partidas.models import Lobby
        from social.models import Invitacion, SolicitudAcceso
        from social.notificaciones import notificar

        with transaction.atomic():
            vigentes = list(
                Lobby.objects.filter(
                    inscripciones__jugador=self,
                    estado__in=(Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO),
                    turno__fin__gt=timezone.now(),
                ).select_related("turno__cancha__club")
            )
            for lobby in vigentes:
                if lobby.es_firme():
                    inicio = timezone.localtime(lobby.turno.inicio)
                    raise Conflicto(
                        "No podés dar de baja tu cuenta: tenés una reserva firme en "
                        f"{lobby.turno.cancha.club.denominacion} el {inicio:%d/%m} "
                        f"a las {inicio:%H:%M}."
                    )
            for lobby in vigentes:
                lobby.abandonar(self)
                notificar(
                    lobby.inscripciones.values_list("jugador__usuario_id", flat=True),
                    f"{self.usuario.username} abandonó la partida.",
                )
            for modelo, campo in ((SolicitudAcceso, "jugador"), (Invitacion, "receptor")):
                modelo.objects.filter(
                    **{campo: self}, estado=modelo.Estado.PENDIENTE
                ).update(estado=modelo.Estado.EXPIRADA)
            self.usuario.is_active = False
            self.usuario.save(update_fields=["is_active"])

    def __str__(self):
        return str(self.usuario)
