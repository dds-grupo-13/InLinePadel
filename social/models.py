from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Greatest, Least

from config.exceptions import Conflicto


ESTADO_PENDIENTE = "PENDIENTE"


class Notificacion(models.Model):
    mensaje = models.TextField()
    leida = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)

    usuario = models.ForeignKey(
        "usuarios.Usuario",
        on_delete=models.CASCADE,
        related_name="notificaciones",
    )

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"
        ordering = ["-fecha"]

    def __str__(self):
        return f"Notificación para {self.usuario_id}"


class Contacto(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ESTADO_PENDIENTE, "Pendiente"
        ACEPTADO = "ACEPTADO", "Aceptado"
        RECHAZADO = "RECHAZADO", "Rechazado"

    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="contactos_enviados",
    )
    contacto = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="contactos_recibidos",
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contacto"
        verbose_name_plural = "Contactos"
        ordering = ["-fecha"]

        constraints = [
            models.UniqueConstraint(
                Least("jugador", "contacto"),
                Greatest("jugador", "contacto"),
                name="contacto_unico_por_par",
            ),
            models.CheckConstraint(
                condition=~models.Q(jugador=models.F("contacto")),
                name="contacto_distinto_de_jugador",
            ),
        ]

    def __str__(self):
        return f"{self.jugador_id} -> {self.contacto_id} ({self.estado})"


class _PedidoLobby:
    def save(self, *args, **kwargs):
        if self._state.adding:
            self.full_clean()
        super().save(*args, **kwargs)

    def _validar_lobby_abierto(self):
        if self.lobby.estado != self.lobby.Estado.EN_FORMACION:
            raise ValidationError("El lobby no está en formación.")

    def _validar_no_inscripto(self, jugador, campo):
        if self.lobby.inscripciones.filter(jugador=jugador).exists():
            raise ValidationError({campo: "El jugador ya está inscripto en el lobby."})

    def _transicionar(self, nuevo):
        cambiado = type(self).objects.filter(
            pk=self.pk, estado=self.Estado.PENDIENTE
        ).update(estado=nuevo)
        if not cambiado:
            raise Conflicto("El pedido ya no está pendiente.")
        self.estado = nuevo

    def aceptar(self):
        with transaction.atomic():
            # Mismo orden de locks que Lobby.cancelar: primero el lobby y
            # después sus pedidos, para no generar deadlocks.
            type(self.lobby).objects.select_for_update().get(pk=self.lobby_id)
            self._transicionar(self.Estado.ACEPTADA)
            self.lobby.inscribir(self.jugador_a_inscribir)

    def rechazar(self):
        self._transicionar(self.Estado.RECHAZADA)


class SolicitudAcceso(_PedidoLobby, models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ESTADO_PENDIENTE, "Pendiente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        EXPIRADA = "EXPIRADA", "Expirada"

    lobby = models.ForeignKey(
        "partidas.Lobby",
        on_delete=models.CASCADE,
        related_name="solicitudes_acceso",
    )
    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="solicitudes_acceso",
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Solicitud de acceso"
        verbose_name_plural = "Solicitudes de acceso"
        ordering = ["-fecha"]

        constraints = [
            models.UniqueConstraint(
                fields=["lobby", "jugador"],
                condition=models.Q(estado=ESTADO_PENDIENTE),
                name="solicitud_pendiente_unica_por_lobby",
            ),
        ]

    @property
    def jugador_a_inscribir(self):
        return self.jugador

    def clean(self):
        super().clean()
        if not (self.lobby_id and self.jugador_id):
            return
        if self.lobby.privacidad != self.lobby.Privacidad.PRIVADO:
            raise ValidationError("Solo se puede pedir acceso a un lobby privado.")
        self._validar_lobby_abierto()
        self._validar_no_inscripto(self.jugador, "jugador")

    def __str__(self):
        return f"Solicitud de {self.jugador_id} a lobby {self.lobby_id}"


class Invitacion(_PedidoLobby, models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = ESTADO_PENDIENTE, "Pendiente"
        ACEPTADA = "ACEPTADA", "Aceptada"
        RECHAZADA = "RECHAZADA", "Rechazada"
        EXPIRADA = "EXPIRADA", "Expirada"

    lobby = models.ForeignKey(
        "partidas.Lobby",
        on_delete=models.CASCADE,
        related_name="invitaciones",
    )
    emisor = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="invitaciones_enviadas",
    )
    receptor = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="invitaciones_recibidas",
    )
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invitación"
        verbose_name_plural = "Invitaciones"
        ordering = ["-fecha"]

        constraints = [
            models.UniqueConstraint(
                fields=["lobby", "receptor"],
                condition=models.Q(estado=ESTADO_PENDIENTE),
                name="invitacion_pendiente_unica_por_lobby",
            ),
            models.CheckConstraint(
                condition=~models.Q(emisor=models.F("receptor")),
                name="invitacion_emisor_distinto_de_receptor",
            ),
        ]

    @property
    def jugador_a_inscribir(self):
        return self.receptor

    def clean(self):
        super().clean()
        if not (self.lobby_id and self.emisor_id and self.receptor_id):
            return
        self._validar_lobby_abierto()
        if not self.lobby.inscripciones.filter(jugador=self.emisor).exists():
            raise ValidationError({"emisor": "Solo un inscripto puede invitar al lobby."})
        self._validar_no_inscripto(self.receptor, "receptor")

    def __str__(self):
        return f"Invitación {self.emisor_id} -> {self.receptor_id} (lobby {self.lobby_id})"
