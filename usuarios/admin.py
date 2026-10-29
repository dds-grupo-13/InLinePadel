from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Jugador, Usuario

admin.site.register(Usuario, UserAdmin)


@admin.register(Jugador)
class JugadorAdmin(admin.ModelAdmin):
    list_display = ["usuario", "posicion", "zona"]
