from django.contrib import admin

from .models import Inscripcion, Lobby


@admin.register(Lobby)
class LobbyAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "privacidad",
        "estado",
        "fecha_creacion",
        "plazo_limite",
        "fecha_check_in",
        "codigo_reserva",
        "cancelada_por",
        "motivo_cancelacion",
        "capitan",
        "turno",
    ]


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ["id", "lobby", "jugador", "numero_cupo", "fecha_inscripcion"]
