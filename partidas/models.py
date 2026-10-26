import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from config.exceptions import Conflicto, ErrorDominio


ESTADO_CANCELADO = "CANCELADO"

class Lobby(models.Model):
    CANTIDAD_CUPOS = 4
    MAX_LOBBIES_EN_FORMACION = 2
    HORAS_PLAZO = 48
    HORAS_PLAZO_REAPERTURA = 12
    MINUTOS_ANTICIPO_CHECK_IN = 15

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

    codigo_reserva = models.CharField(
        max_length=9, unique=True, null=True, blank=True, editable=False
    )

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
            models.Index(fields=["estado", "privacidad"], name="lobby_estado_privacidad_idx"),
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


    @property
    def estado_reserva(self):
        return {
            self.Estado.EN_FORMACION: "PROVISORIA",
            self.Estado.COMPLETO: "CONFIRMADA",
            self.Estado.JUGADO: "CUMPLIDA",
        }.get(self.estado)

    @classmethod
    def conflicto_horario(cls, jugador, turno, excluir_lobby=None):
        vigentes = cls.objects.filter(
            inscripciones__jugador=jugador,
            estado__in=(cls.Estado.EN_FORMACION, cls.Estado.COMPLETO),
            turno__inicio__lt=turno.fin,
            turno__fin__gt=turno.inicio,
        )
        if excluir_lobby is not None:
            vigentes = vigentes.exclude(pk=excluir_lobby)
        return vigentes.select_related("turno").first()

    @classmethod
    def crear(cls, turno, capitan, **campos):
        Turno = cls._meta.get_field("turno").related_model
        campos.setdefault("fecha_check_in", turno.inicio)
        campos.setdefault(
            "plazo_limite",
            min(timezone.now() + timedelta(hours=cls.HORAS_PLAZO), turno.inicio),
        )
        if turno.cancha.club.estado != "ACTIVO":
            raise ErrorDominio("El club no está habilitado para recibir reservas.")
        if not turno.cancha.activa:
            raise ErrorDominio("La cancha no está habilitada para recibir reservas.")
        if turno.inicio <= timezone.now():
            raise ErrorDominio("El turno ya comenzó o ya pasó.")
        with transaction.atomic():
            Jugador = cls._meta.get_field("capitan").related_model
            Jugador.objects.select_for_update().filter(pk=capitan.pk).first()
            en_formacion = cls.objects.filter(
                capitan=capitan, estado=cls.Estado.EN_FORMACION
            ).count()
            if en_formacion >= cls.MAX_LOBBIES_EN_FORMACION:
                raise ErrorDominio(
                    f"Ya sos capitán de {cls.MAX_LOBBIES_EN_FORMACION} partidas en formación. "
                    "Esperá a que se completen o cancelá una."
                )
            superpuesto = cls.conflicto_horario(capitan, turno)
            if superpuesto:
                raise ErrorDominio(
                    "Ya participás de otra partida en ese horario "
                    f"({timezone.localtime(superpuesto.turno.inicio):%d/%m %H:%M})."
                )
            bloqueado = Turno.objects.filter(
                pk=turno.pk, estado=Turno.Estado.LIBRE
            ).update(estado=Turno.Estado.BLOQUEADO)
            if not bloqueado:
                raise Conflicto("El turno ya fue tomado por otro jugador.")
            turno.estado = Turno.Estado.BLOQUEADO
            lobby = cls(turno=turno, capitan=capitan, **campos)
            lobby.full_clean()
            lobby.save()
            Inscripcion.objects.create(lobby=lobby, jugador=capitan, numero_cupo=1)
            from social.notificaciones import notificar

            notificar(
                [turno.cancha.club.admin_id],
                f"Turno {turno.fecha:%d/%m} {turno.hora_inicio:%H:%M} "
                f"(cancha {turno.cancha.numero}) reservado provisoriamente.",
            )
            return lobby

    def inscribir(self, jugador):
        for _ in range(self.CANTIDAD_CUPOS):
            with transaction.atomic():
                type(jugador).objects.select_for_update().filter(pk=jugador.pk).first()
                superpuesto = Lobby.conflicto_horario(
                    jugador, self.turno, excluir_lobby=self.pk
                )
                if superpuesto:
                    raise Conflicto(
                        "Ya participás de otra partida en ese horario "
                        f"({timezone.localtime(superpuesto.turno.inicio):%d/%m %H:%M})."
                    )
                estado = Lobby.objects.values_list("estado", flat=True).get(pk=self.pk)
                if estado != self.Estado.EN_FORMACION:
                    raise Conflicto("La partida ya no está abierta a nuevos jugadores.")
                ocupados = set(
                    Inscripcion.objects.filter(lobby_id=self.pk).values_list(
                        "numero_cupo", flat=True
                    )
                )
                libres = [
                    n for n in range(1, self.CANTIDAD_CUPOS + 1) if n not in ocupados
                ]
                if not libres:
                    raise Conflicto("El partido ya está completo.")
                try:
                    with transaction.atomic():
                        inscripcion = Inscripcion.objects.create(
                            lobby_id=self.pk, jugador=jugador, numero_cupo=libres[0]
                        )
                except IntegrityError:
                    if Inscripcion.objects.filter(lobby_id=self.pk, jugador=jugador).exists():
                        raise ErrorDominio("El jugador ya está inscripto en este lobby")
                    continue
                if len(ocupados) + 1 >= self.CANTIDAD_CUPOS:
                    Lobby.objects.filter(
                        pk=self.pk, estado=self.Estado.EN_FORMACION
                    ).update(estado=self.Estado.COMPLETO)
                    self.estado = self.Estado.COMPLETO
                    self._confirmar_reserva()
                    self._expirar_pendientes()
                return inscripcion
        raise ErrorDominio("No se pudo asignar un cupo, reintentá")

    def abandonar(self, jugador):
        with transaction.atomic():
            lobby = Lobby.objects.get(pk=self.pk)
            if lobby.estado not in (self.Estado.EN_FORMACION, self.Estado.COMPLETO):
                raise ErrorDominio(f"No se puede abandonar un lobby {lobby.estado}")
            borradas, _ = Inscripcion.objects.filter(
                lobby_id=self.pk, jugador=jugador
            ).delete()
            if not borradas:
                raise ErrorDominio("El jugador no está inscripto en este lobby")

            reabierto = Lobby.objects.filter(
                pk=self.pk, estado=self.Estado.COMPLETO
            ).update(estado=self.Estado.EN_FORMACION)
            if reabierto:
                Turno = self._meta.get_field("turno").related_model
                plazo = max(
                    lobby.plazo_limite,
                    min(
                        timezone.now() + timedelta(hours=self.HORAS_PLAZO_REAPERTURA),
                        lobby.fecha_check_in,
                    ),
                )
                Lobby.objects.filter(pk=self.pk).update(codigo_reserva=None, plazo_limite=plazo)
                self.codigo_reserva = None
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
                raise ErrorDominio("Solo se puede cancelar un lobby en formación o completo")
            Turno.objects.filter(
                pk=self.turno_id,
                estado__in=(Turno.Estado.BLOQUEADO, Turno.Estado.CONFIRMADO),
            ).update(estado=Turno.Estado.LIBRE)
            self.estado = self.Estado.CANCELADO
            self._expirar_pendientes()
            self._notificar_liberacion()

    def _confirmar_reserva(self):
        from social.notificaciones import notificar

        Turno = self._meta.get_field("turno").related_model
        Turno.objects.filter(pk=self.turno_id, estado=Turno.Estado.BLOQUEADO).update(
            estado=Turno.Estado.CONFIRMADO
        )
        for _ in range(10):
            codigo = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper()
            if not Lobby.objects.filter(codigo_reserva=codigo).exists():
                break
        Lobby.objects.filter(pk=self.pk).update(codigo_reserva=codigo)
        self.codigo_reserva = codigo
        turno = self.turno
        jugadores = list(
            self.inscripciones.values_list("jugador__usuario_id", flat=True)
        )
        notificar(
            jugadores,
            f"Reserva confirmada para el {turno.fecha:%d/%m} a las "
            f"{turno.hora_inicio:%H:%M} — código {codigo}.",
        )
        notificar(
            [turno.cancha.club.admin_id],
            f"Cancha {turno.cancha.numero} vendida el {turno.fecha:%d/%m} "
            f"a las {turno.hora_inicio:%H:%M}.",
        )

    def _notificar_liberacion(self):
        from social.notificaciones import notificar

        turno = self.turno
        usuarios = list(self.inscripciones.values_list("jugador__usuario_id", flat=True))
        usuarios.append(turno.cancha.club.admin_id)
        notificar(
            usuarios,
            f"Se canceló la partida del {turno.fecha:%d/%m} a las "
            f"{turno.hora_inicio:%H:%M}; el turno quedó libre.",
        )

    def _expirar_pendientes(self):
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
