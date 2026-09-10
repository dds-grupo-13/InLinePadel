from django.db import models


class Lobby(models.Model):
    CANTIDAD_CUPOS = 4

    class Estado(models.TextChoices):
        EN_FORMACION = "EN_FORMACION", "En formación"
        COMPLETO = "COMPLETO", "Completo"
        JUGADO = "JUGADO", "Jugado"
        CANCELADO = "CANCELADO", "Cancelado"

    class Privacidad(models.TextChoices):
        PUBLICO = "PUBLICO", "Público"
        SOLO_AMIGOS = "SOLO_AMIGOS", "Solo amigos"

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    privacidad = models.CharField(
        max_length=12,
        choices=Privacidad.choices,
        default=Privacidad.PUBLICO,
    )
    plazo_limite = models.DateTimeField()
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.EN_FORMACION,
    )

    class Meta:
        verbose_name = "Lobby"
        verbose_name_plural = "Lobbies"

    def __str__(self):
        return f"Lobby #{self.pk} [{self.estado}]"

    @property
    def capitan(self):
        insc = self.inscripciones.filter(rol=Inscripcion.Rol.CAPITAN).first()
        return insc.jugador if insc else None

    def cupos_ocupados(self) -> int:
        return self.inscripciones.count()


class Reserva(models.Model):
    class Estado(models.TextChoices):
        PROVISORIA = "PROVISORIA", "Provisoria"
        CONFIRMADA = "CONFIRMADA", "Confirmada"
        CUMPLIDA = "CUMPLIDA", "Cumplida"
        CANCELADA = "CANCELADA", "Cancelada"

    lobby = models.OneToOneField(
        Lobby,
        on_delete=models.CASCADE,
        related_name="reserva",
    )
    turno = models.OneToOneField(
        "clubes.Turno",
        on_delete=models.PROTECT,
        related_name="reserva",
    )
    codigo_reserva = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        default=None,
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PROVISORIA,
    )
    fecha_check_in = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = "Reserva"
        verbose_name_plural = "Reservas"

    def __str__(self):
        return f"Reserva #{self.pk} [{self.estado}]"


class Inscripcion(models.Model):
    class Rol(models.TextChoices):
        CAPITAN = "CAPITAN", "Capitán"
        JUGADOR = "JUGADOR", "Jugador"

    lobby = models.ForeignKey(
        Lobby,
        on_delete=models.CASCADE,
        related_name="inscripciones",
    )
    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="inscripciones",
    )
    numero_cupo = models.PositiveSmallIntegerField()
    rol = models.CharField(max_length=8, choices=Rol.choices, default=Rol.JUGADOR)
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Inscripción"
        verbose_name_plural = "Inscripciones"
        constraints = [
            models.UniqueConstraint(
                fields=["lobby", "jugador"],
                name="jugador_unico_por_lobby",
            ),
            models.UniqueConstraint(
                fields=["lobby", "numero_cupo"],
                name="cupo_unico_por_lobby",
            ),
        ]

    def __str__(self):
        return f"{self.jugador} en Lobby #{self.lobby_id} (cupo {self.numero_cupo})"
