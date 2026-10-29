from django.contrib import admin

from .models import Cancha, Club, Turno, Zona


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ["id", "nombre"]


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ["id", "denominacion", "direccion", "estado", "zona", "admin"]


@admin.register(Cancha)
class CanchaAdmin(admin.ModelAdmin):
    list_display = ["id", "numero", "activa", "tipo", "club"]


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "fecha",
        "hora_inicio",
        "duracion",
        "precio",
        "estado",
        "cancha",
        "inicio",
        "fin",
    ]
