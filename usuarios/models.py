from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone


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
        """Desactiva al usuario sin dejar partidas colgadas.

        Sale de los lobbies vigentes (si era capitán la capitanía pasa al
        siguiente inscripto o el lobby se cancela) y vence sus pedidos pendientes.
        """
        # imports locales: partidas y social dependen de usuarios, no al revés
        from partidas.models import Lobby
        from social.models import Invitacion, SolicitudAcceso
        from social.notificaciones import notificar

        with transaction.atomic():
            vigentes = Lobby.objects.filter(
                inscripciones__jugador=self,
                estado__in=(Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO),
                turno__fin__gt=timezone.now(),
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
