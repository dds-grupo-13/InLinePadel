from django.db import models

class Contacto(models.Model):

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ACEPTADO = "ACEPTADO", "Aceptado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="contactos_iniciados",
    )
    contacto = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="contactos_recibidos",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    class Meta:
        verbose_name = "Contacto"
        verbose_name_plural = "Contactos"
        constraints = [
            models.UniqueConstraint(
                fields=["jugador", "contacto"],
                name="contacto_unico_por_par",
            ),
        ]

    def __str__(self):
        return f"{self.jugador} - {self.contacto} [{self.estado}]"


class Invitacion(models.Model):

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        EXPIRADA = "EXPIRADA", "Expirada"

    lobby = models.ForeignKey(
        "partidas.Lobby",
        on_delete=models.CASCADE,
        related_name="invitaciones",
    )

    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="invitaciones_recibidas",
    )

    emisor = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="invitaciones_enviadas",
        blank=True,
        null=True,
    )
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    class Meta:
        verbose_name = "Invitación"
        verbose_name_plural = "Invitaciones"

    def __str__(self):
        return f"Invitación a {self.jugador} (Lobby #{self.lobby_id}) [{self.estado}]"


class SolicitudAcceso(models.Model):

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    lobby = models.ForeignKey(
        "partidas.Lobby",
        on_delete=models.CASCADE,
        related_name="solicitudes",
    )

    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="solicitudes_enviadas",
    )
    fecha = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    class Meta:
        verbose_name = "Solicitud de acceso"
        verbose_name_plural = "Solicitudes de acceso"

    def __str__(self):
        return f"Solicitud de {self.jugador} (Lobby #{self.lobby_id}) [{self.estado}]"
