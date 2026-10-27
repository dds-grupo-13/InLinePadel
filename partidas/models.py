import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from config.exceptions import Conflicto, ErrorDominio


ESTADO_CANCELADO = "CANCELADO"
ESTADO_EN_FORMACION = "EN_FORMACION"

class Lobby(models.Model):
    CANTIDAD_CUPOS = 4
    MAX_LOBBIES_EN_FORMACION = 2
    HORAS_PLAZO = 48
    HORAS_PLAZO_REAPERTURA = 12
    HORAS_CIERRE = 3
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

    class CanceladaPor(models.TextChoices):
        CAPITAN = "CAPITAN", "Capitán"
        ABANDONO = "ABANDONO", "Abandono del último jugador"
        VENCIMIENTO = "VENCIMIENTO", "Vencimiento del plazo"
        CLUB = "CLUB", "Club"
        SISTEMA = "SISTEMA", "Sistema"

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    plazo_limite = models.DateTimeField()
    fecha_check_in = models.DateTimeField()

    codigo_reserva = models.CharField(
        max_length=9, unique=True, null=True, blank=True, editable=False
    )

    cancelada_por = models.CharField(
        max_length=12, choices=CanceladaPor.choices, null=True, blank=True, editable=False
    )
    motivo_cancelacion = models.CharField(max_length=200, blank=True, editable=False)

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


    @staticmethod
    def q_vencido(ahora=None):
        return models.Q(
            estado=ESTADO_EN_FORMACION, plazo_limite__lt=ahora or timezone.now()
        )

    def esta_vencido(self, ahora=None):
        return self.estado == ESTADO_EN_FORMACION and self.plazo_limite < (
            ahora or timezone.now()
        )

    def vencer_si_corresponde(self, ahora=None):
        """Cancela por VENCIMIENTO si el plazo ya pasó. Devuelve True si lo hizo.

        No llamarlo dentro de una transacción externa que después se revierta:
        si la vista lanza 409 dentro del mismo `atomic`, el vencimiento se pierde.
        Por eso las vistas lo llaman antes de abrir su propia transacción.
        """
        if not self.esta_vencido(ahora):
            return False
        vencido = False
        with transaction.atomic():
            lobby = Lobby.objects.select_for_update().get(pk=self.pk)
            # Otro proceso pudo haberlo completado, cancelado o vencido ya.
            if lobby.esta_vencido(ahora):
                self._cancelar(self.CanceladaPor.VENCIMIENTO)
                vencido = True
        self.refresh_from_db(fields=["estado", "cancelada_por"])
        return vencido

    @classmethod
    def vencer_del_turno(cls, turno, ahora=None):
        lobby = cls.objects.filter(cls.q_vencido(ahora), turno=turno).first()
        return lobby is not None and lobby.vencer_si_corresponde(ahora)

    @property
    def estado_reserva(self):
        return {
            self.Estado.EN_FORMACION: "PROVISORIA",
            self.Estado.COMPLETO: "CONFIRMADA",
            self.Estado.JUGADO: "CUMPLIDA",
        }.get(self.estado)

    @staticmethod
    def cierre_de(turno):
        return turno.inicio - timedelta(hours=Lobby.HORAS_CIERRE)

    @property
    def cierre(self):
        return self.cierre_de(self.turno)

    def es_firme(self, ahora=None):
        return self.estado == self.Estado.COMPLETO and (
            ahora or timezone.now()
        ) >= self.cierre

    def puede_cancelar(self, jugador):
        return self.capitan_id == jugador.pk and self.estado == self.Estado.EN_FORMACION

    def puede_abandonar(self, jugador, ahora=None):
        return (
            self.estado in (self.Estado.EN_FORMACION, self.Estado.COMPLETO)
            and not self.es_firme(ahora)
            and any(i.jugador_id == jugador.pk for i in self.inscripciones.all())
        )

    @classmethod
    def conflicto_horario(cls, jugador, turno, excluir_lobby=None):
        vigentes = cls.objects.filter(
            inscripciones__jugador=jugador,
            estado__in=(cls.Estado.EN_FORMACION, cls.Estado.COMPLETO),
            turno__inicio__lt=turno.fin,
            turno__fin__gt=turno.inicio,
        ).exclude(cls.q_vencido())
        if excluir_lobby is not None:
            vigentes = vigentes.exclude(pk=excluir_lobby)
        return vigentes.select_related("turno").first()

    @classmethod
    def crear(cls, turno, capitan, **campos):
        Turno = cls._meta.get_field("turno").related_model
        ahora = timezone.now()
        cierre = cls.cierre_de(turno)
        campos.setdefault("fecha_check_in", turno.inicio)
        # Una partida de último momento (creada dentro de la ventana de cierre)
        # tiene plazo hasta el inicio: apenas se completa, queda firme.
        campos.setdefault(
            "plazo_limite",
            min(ahora + timedelta(hours=cls.HORAS_PLAZO), cierre)
            if ahora < cierre
            else turno.inicio,
        )
        if turno.cancha.club.estado != "ACTIVO":
            raise ErrorDominio("El club no está habilitado para recibir reservas.")
        if not turno.cancha.activa:
            raise ErrorDominio("La cancha no está habilitada para recibir reservas.")
        if turno.inicio <= timezone.now():
            raise ErrorDominio("El turno ya comenzó o ya pasó.")
        with transaction.atomic():
            # Primero el lock del lobby viejo y después el del jugador (mismo
            # orden que `inscribir`).
            cls.vencer_del_turno(turno, ahora)
            Jugador = cls._meta.get_field("capitan").related_model
            Jugador.objects.select_for_update().filter(pk=capitan.pk).first()
            en_formacion = (
                cls.objects.filter(capitan=capitan, estado=cls.Estado.EN_FORMACION)
                .exclude(plazo_limite__lt=ahora)
                .count()
            )
            if en_formacion >= cls.MAX_LOBBIES_EN_FORMACION:
                raise ErrorDominio(
                    f"Ya sos capitán de {cls.MAX_LOBBIES_EN_FORMACION} partidas en formación. "
                    "Esperá a que se completen o cancelá una."
                )
            superpuesto = cls.conflicto_horario(capitan, turno)
            if superpuesto:
                raise Conflicto(
                    "Ya participás de otra partida en ese horario "
                    f"({timezone.localtime(superpuesto.turno.inicio):%d/%m %H:%M})."
                )
            bloqueado = Turno.objects.filter(
                pk=turno.pk, estado=Turno.Estado.LIBRE
            ).update(estado=Turno.Estado.BLOQUEADO)
            if not bloqueado:
                cls._rechazar_turno_no_libre(turno)
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

    @classmethod
    def _rechazar_turno_no_libre(cls, turno):
        Turno = cls._meta.get_field("turno").related_model
        actual = (
            Turno.objects.filter(pk=turno.pk).values_list("estado", flat=True).first()
        )
        if actual == Turno.Estado.NO_DISPONIBLE:
            raise Conflicto("El club retiró este turno de la oferta.")
        if actual == Turno.Estado.CUMPLIDO:
            raise ErrorDominio("El turno ya pasó.")
        raise Conflicto("El turno ya fue tomado por otro jugador.")

    def inscribir(self, jugador):
        # Orden de locks: primero el lobby, después el jugador. Quien tome los
        # locks en otro orden (ver _PedidoLobby.aceptar) puede generar deadlocks.
        for _ in range(self.CANTIDAD_CUPOS):
            with transaction.atomic():
                lobby = Lobby.objects.select_for_update().get(pk=self.pk)
                type(jugador).objects.select_for_update().filter(pk=jugador.pk).first()
                superpuesto = Lobby.conflicto_horario(
                    jugador, self.turno, excluir_lobby=self.pk
                )
                if superpuesto:
                    raise Conflicto(
                        "Ya participás de otra partida en ese horario "
                        f"({timezone.localtime(superpuesto.turno.inicio):%d/%m %H:%M})."
                    )
                if lobby.estado != self.Estado.EN_FORMACION:
                    raise Conflicto("La partida ya no está abierta a nuevos jugadores.")
                if lobby.esta_vencido():
                    raise Conflicto("Venció el plazo para completar esta partida.")
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
                    # Defensa: las restricciones únicas siguen vigentes aunque el
                    # lock del lobby ya serializa las inscripciones.
                    if Inscripcion.objects.filter(lobby_id=self.pk, jugador=jugador).exists():
                        raise ErrorDominio("El jugador ya está inscripto en este lobby")
                    continue
                if len(ocupados) + 1 >= self.CANTIDAD_CUPOS:
                    completado = Lobby.objects.filter(
                        pk=self.pk, estado=self.Estado.EN_FORMACION
                    ).update(estado=self.Estado.COMPLETO)
                    if not completado:
                        raise Conflicto("La partida ya no está abierta a nuevos jugadores.")
                    self.estado = self.Estado.COMPLETO
                    self._confirmar_reserva()
                    self._expirar_pendientes()
                return inscripcion
        raise ErrorDominio("No se pudo asignar un cupo, reintentá")

    def abandonar(self, jugador):
        from social.notificaciones import notificar

        with transaction.atomic():
            lobby = Lobby.objects.select_for_update().get(pk=self.pk)
            if lobby.estado not in (self.Estado.EN_FORMACION, self.Estado.COMPLETO):
                raise Conflicto(f"No se puede abandonar un lobby {lobby.estado}")
            if not Inscripcion.objects.filter(lobby_id=self.pk, jugador=jugador).exists():
                raise ErrorDominio("El jugador no está inscripto en este lobby")
            ahora = timezone.now()
            if lobby.es_firme(ahora):
                desde = timezone.localtime(lobby.cierre)
                raise Conflicto(
                    f"La reserva ya es firme desde las {desde:%H:%M}: no podés bajarte. "
                    "Podés ceder tu lugar a un contacto."
                )
            Inscripcion.objects.filter(lobby_id=self.pk, jugador=jugador).delete()
            self._expirar_cesiones(jugador)

            reabierto = Lobby.objects.filter(
                pk=self.pk, estado=self.Estado.COMPLETO
            ).update(estado=self.Estado.EN_FORMACION)
            if reabierto:
                # Una cesión solo tiene sentido con la partida completa.
                self._expirar_cesiones()
                Turno = self._meta.get_field("turno").related_model
                plazo = min(
                    max(
                        lobby.plazo_limite,
                        ahora + timedelta(hours=self.HORAS_PLAZO_REAPERTURA),
                    ),
                    lobby.cierre,
                    lobby.fecha_check_in,
                )
                Lobby.objects.filter(pk=self.pk).update(codigo_reserva=None, plazo_limite=plazo)
                self.codigo_reserva = None
                Turno.objects.filter(
                    pk=self.turno_id, estado=Turno.Estado.CONFIRMADO
                ).update(estado=Turno.Estado.BLOQUEADO)
                turno = self.turno
                notificar(
                    [turno.cancha.club.admin_id],
                    f"La reserva de la cancha {turno.cancha.numero} del "
                    f"{turno.fecha:%d/%m} {turno.hora_inicio:%H:%M} volvió a provisoria.",
                )

            if lobby.capitan_id == jugador.pk:
                siguiente = (
                    Inscripcion.objects.filter(lobby_id=self.pk)
                    .order_by("fecha_inscripcion", "pk")
                    .first()
                )
                if siguiente is None:
                    self._cancelar(self.CanceladaPor.ABANDONO)
                else:
                    Lobby.objects.filter(pk=self.pk).update(
                        capitan_id=siguiente.jugador_id
                    )
            self.refresh_from_db(fields=["estado", "capitan"])

    def cancelar_por_capitan(self, jugador):
        with transaction.atomic():
            lobby = Lobby.objects.select_for_update().get(pk=self.pk)
            if lobby.capitan_id != jugador.pk:
                raise ErrorDominio("Solo el capitán de la partida puede cancelarla.")
            if lobby.estado == self.Estado.COMPLETO:
                if lobby.es_firme():
                    raise Conflicto(
                        "La partida ya está completa y la reserva ya es firme: "
                        "no se puede cancelar."
                    )
                hasta = timezone.localtime(lobby.cierre)
                raise Conflicto(
                    "La partida ya está completa: no se puede cancelar. "
                    f"Cada jugador puede bajarse hasta el {hasta:%d/%m %H:%M}."
                )
            self._cancelar(self.CanceladaPor.CAPITAN)

    def _cancelar(self, por, motivo="", estado_turno=None):
        # Solo `por=CLUB` debe usarse sobre un lobby COMPLETO: la validación de las
        # reglas de cancelación del capitán vive en cancelar_por_capitan.
        Turno = self._meta.get_field("turno").related_model
        with transaction.atomic():
            Lobby.objects.select_for_update().get(pk=self.pk)
            cancelado = Lobby.objects.filter(
                pk=self.pk,
                estado__in=(self.Estado.EN_FORMACION, self.Estado.COMPLETO),
            ).update(
                estado=self.Estado.CANCELADO, cancelada_por=por, motivo_cancelacion=motivo
            )
            if not cancelado:
                raise ErrorDominio("Solo se puede cancelar una partida en formación o completa")
            Turno.objects.filter(
                pk=self.turno_id,
                estado__in=(Turno.Estado.BLOQUEADO, Turno.Estado.CONFIRMADO),
            ).update(estado=estado_turno or Turno.Estado.LIBRE)
            self.estado = self.Estado.CANCELADO
            self.cancelada_por = por
            self.motivo_cancelacion = motivo
            self._expirar_pendientes()
            self._notificar_cancelacion(por, motivo)

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

    def _notificar_cancelacion(self, por, motivo):
        from social.notificaciones import notificar

        turno = self.turno
        usuarios = list(self.inscripciones.values_list("jugador__usuario_id", flat=True))
        if por == self.CanceladaPor.CLUB:
            notificar(
                usuarios,
                f"El club {turno.cancha.club.denominacion} canceló la partida del "
                f"{turno.fecha:%d/%m} a las {turno.hora_inicio:%H:%M}: {motivo}.",
            )
            return
        usuarios.append(turno.cancha.club.admin_id)
        if por == self.CanceladaPor.VENCIMIENTO:
            notificar(
                usuarios,
                f"Venció el plazo de la partida del {turno.fecha:%d/%m} a las "
                f"{turno.hora_inicio:%H:%M} sin completar los cupos: se canceló "
                "y el turno quedó libre.",
            )
            return
        notificar(
            usuarios,
            f"Se canceló la partida del {turno.fecha:%d/%m} a las "
            f"{turno.hora_inicio:%H:%M}; el turno quedó libre.",
        )

    def _expirar_cesiones(self, emisor=None):
        from social.models import Invitacion

        cesiones = Invitacion.objects.filter(
            lobby_id=self.pk, estado=Invitacion.Estado.PENDIENTE, reemplaza__isnull=False
        )
        if emisor is not None:
            cesiones = cesiones.filter(reemplaza=emisor)
        cesiones.update(estado=Invitacion.Estado.EXPIRADA)

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
