from django.contrib.auth.models import AbstractUser
from django.db import models


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

    def __str__(self):
        return str(self.usuario)
