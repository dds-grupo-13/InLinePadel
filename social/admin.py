from django.contrib import admin

from .models import Contacto, Invitacion, Notificacion, SolicitudAcceso


@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ["id", "mensaje", "leida", "fecha", "usuario"]


@admin.register(Contacto)
class ContactoAdmin(admin.ModelAdmin):
    list_display = ["id", "jugador", "contacto", "estado", "fecha"]


@admin.register(SolicitudAcceso)
class SolicitudAccesoAdmin(admin.ModelAdmin):
    list_display = ["id", "lobby", "jugador", "estado", "fecha"]


@admin.register(Invitacion)
class InvitacionAdmin(admin.ModelAdmin):
    list_display = ["id", "lobby", "emisor", "receptor", "estado", "reemplaza", "fecha"]
