from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

# Create your models here.

ESTADO_CANCELADO = "CANCELADO"

class Lobby(models.Model):
    CANTIDAD_CUPOS = 4

    class Estado(models.TextChoices):
        EN_FORMACION = "EN_FORMACION", "En formación"
        COMPLETO = "COMPLETO", "Completo"
        JUGADO = "JUGADO", "Jugado"
        CANCELADO = ESTADO_CANCELADO, "Cancelado"

    class Privacidad(models.TextChoices):
        PUBLICO = "PUBLICO", "Público"
        PRIVADO = "PRIVADO", "Privado"

    privacidad = models.CharField(
        max_length=12,
        choices=Privacidad.choices,
        default=Privacidad.PUBLICO,
    )

    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.EN_FORMACION,
    )

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    plazo_limite = models.DateTimeField()
    fecha_check_in = models.DateTimeField()

    capitan = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="lobbies_capitaneados",
    )

    turno = models.ForeignKey(
        "clubes.Turno",
        on_delete=models.PROTECT,
        related_name="lobbies",
    )

    class Meta:
        verbose_name = "Lobby"
        verbose_name_plural = "Lobbies"

        indexes = [
            # listado de lobbies públicos abiertos
            models.Index(fields=["estado", "privacidad"], name="lobby_estado_privacidad_idx"),
            # barrido de lobbies vencidos
            models.Index(fields=["estado", "plazo_limite"], name="lobby_estado_plazo_idx"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["turno"],
                condition=~models.Q(estado=ESTADO_CANCELADO),
                name="un_lobby_vigente_por_turno",
            ),
            models.CheckConstraint(
                condition=models.Q(plazo_limite__lte=models.F("fecha_check_in")),
                name="lobby_plazo_limite_antes_de_check_in",
            ),
        ]

    def __str__(self):
        return f"Lobby {self.pk} - {self.turno} [{self.estado}]"

    def clean(self):
        super().clean()
        if not (self.turno_id and self.plazo_limite and self.fecha_check_in):
            return
        if self.plazo_limite > self.fecha_check_in:
            raise ValidationError(
                "El plazo límite debe ser anterior o igual al check-in."
            )
        if self.fecha_check_in > self.turno.inicio:
            raise ValidationError("El check-in debe ser anterior al inicio del turno.")

    # Las transiciones de estado usan UPDATE condicional (compare-and-swap): es
    # atómico en cualquier base y no depende de select_for_update (que SQLite ignora).

    @classmethod
    def crear(cls, turno, capitan, **campos):
        """Crea el lobby, bloquea el turno e inscribe al capitán en el cupo 1."""
        Turno = cls._meta.get_field("turno").related_model
        with transaction.atomic():
            bloqueado = Turno.objects.filter(
                pk=turno.pk, estado=Turno.Estado.LIBRE
            ).update(estado=Turno.Estado.BLOQUEADO)
            if not bloqueado:
                raise ValueError("El turno no está libre")
            turno.estado = Turno.Estado.BLOQUEADO
            # full_clean aplica las reglas de clean() (ej: check-in antes del turno);
            # si falla, el atomic revierte el bloqueo del turno
            lobby = cls(turno=turno, capitan=capitan, **campos)
            lobby.full_clean()
            lobby.save()
            Inscripcion.objects.create(lobby=lobby, jugador=capitan, numero_cupo=1)
            return lobby

    def inscribir(self, jugador):
        # Los unique constraints (lobby, cupo) y (lobby, jugador) garantizan la
        # consistencia ante inscripciones concurrentes; si dos toman el mismo
        # cupo, el perdedor reintenta con el siguiente libre.
        for _ in range(self.CANTIDAD_CUPOS):
            with transaction.atomic():
                estado = Lobby.objects.values_list("estado", flat=True).get(pk=self.pk)
                if estado != self.Estado.EN_FORMACION:
                    raise ValueError(f"No se puede inscribir en un lobby {estado}")
                ocupados = set(
                    Inscripcion.objects.filter(lobby_id=self.pk).values_list(
                        "numero_cupo", flat=True
                    )
                )
                libres = [
                    n for n in range(1, self.CANTIDAD_CUPOS + 1) if n not in ocupados
                ]
                if not libres:
                    raise ValueError("El lobby no tiene cupos libres")
                try:
                    with transaction.atomic():
                        inscripcion = Inscripcion.objects.create(
                            lobby_id=self.pk, jugador=jugador, numero_cupo=libres[0]
                        )
                except IntegrityError:
                    if Inscripcion.objects.filter(lobby_id=self.pk, jugador=jugador).exists():
                        raise ValueError("El jugador ya está inscripto en este lobby")
                    continue  # cupo tomado por otro: reintentar
                if len(ocupados) + 1 >= self.CANTIDAD_CUPOS:
                    Lobby.objects.filter(
                        pk=self.pk, estado=self.Estado.EN_FORMACION
                    ).update(estado=self.Estado.COMPLETO)
                    self.estado = self.Estado.COMPLETO
                    # con el lobby completo ya no hay cupo para pedidos pendientes
                    self._expirar_pendientes()
                return inscripcion
        raise ValueError("No se pudo asignar un cupo, reintentá")

    def abandonar(self, jugador):
        """Libera el cupo del jugador. Si era el capitán, pasa al primero en
        haberse inscripto; si no queda nadie, el lobby se cancela."""
        with transaction.atomic():
            lobby = Lobby.objects.get(pk=self.pk)
            if lobby.estado not in (self.Estado.EN_FORMACION, self.Estado.COMPLETO):
                raise ValueError(f"No se puede abandonar un lobby {lobby.estado}")
            borradas, _ = Inscripcion.objects.filter(
                lobby_id=self.pk, jugador=jugador
            ).delete()
            if not borradas:
                raise ValueError("El jugador no está inscripto en este lobby")

            # al liberarse un cupo vuelve a estar abierto; si el turno ya estaba
            # confirmado (via API) deja de estarlo hasta que se complete de nuevo
            reabierto = Lobby.objects.filter(
                pk=self.pk, estado=self.Estado.COMPLETO
            ).update(estado=self.Estado.EN_FORMACION)
            if reabierto:
                Turno = self._meta.get_field("turno").related_model
                Turno.objects.filter(
                    pk=self.turno_id, estado=Turno.Estado.CONFIRMADO
                ).update(estado=Turno.Estado.BLOQUEADO)

            if lobby.capitan_id == jugador.pk:
                siguiente = (
                    Inscripcion.objects.filter(lobby_id=self.pk)
                    .order_by("fecha_inscripcion", "pk")
                    .first()
                )
                if siguiente is None:
                    self.cancelar()
                else:
                    Lobby.objects.filter(pk=self.pk).update(
                        capitan_id=siguiente.jugador_id
                    )
            self.refresh_from_db(fields=["estado", "capitan"])

    def cancelar(self):
        Turno = self._meta.get_field("turno").related_model
        with transaction.atomic():
            cancelado = Lobby.objects.filter(
                pk=self.pk,
                estado__in=(self.Estado.EN_FORMACION, self.Estado.COMPLETO),
            ).update(estado=self.Estado.CANCELADO)
            if not cancelado:
                raise ValueError("Solo se puede cancelar un lobby en formación o completo")
            Turno.objects.filter(
                pk=self.turno_id,
                estado__in=(Turno.Estado.BLOQUEADO, Turno.Estado.CONFIRMADO),
            ).update(estado=Turno.Estado.LIBRE)
            self.estado = self.Estado.CANCELADO
            self._expirar_pendientes()

    def _expirar_pendientes(self):
        """Vence las invitaciones y solicitudes de acceso que siguen pendientes."""
        # import local: social depende de partidas (FK a Lobby), no al revés
        from social.models import Invitacion, SolicitudAcceso

        for modelo in (Invitacion, SolicitudAcceso):
            modelo.objects.filter(
                lobby_id=self.pk, estado=modelo.Estado.PENDIENTE
            ).update(estado=modelo.Estado.EXPIRADA)


class Inscripcion(models.Model):
    lobby = models.ForeignKey(
        Lobby,
        on_delete=models.CASCADE,
        related_name="inscripciones"
    )

    # PROTECT: conserva el historial; un usuario se desactiva (is_active=False)
    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.PROTECT,
        related_name="inscripciones",
    )
    numero_cupo = models.PositiveSmallIntegerField()
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Inscripción"
        verbose_name_plural = "Inscripciones"
        ordering = ["lobby", "numero_cupo"]

        constraints = [
            models.UniqueConstraint(
                fields=["lobby", "numero_cupo"],
                name="cupo_unico_por_lobby",
            ),
            models.UniqueConstraint(
                fields=["lobby", "jugador"],
                name="jugador_unico_por_lobby",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    numero_cupo__gte=1,
                    numero_cupo__lte=Lobby.CANTIDAD_CUPOS,
                ),
                name="numero_cupo_en_rango",
            ),
        ]

    def __str__(self):
        return f"Cupo {self.numero_cupo} - Lobby {self.lobby_id}"
