from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Jugador, Usuario

admin.site.register(Usuario, UserAdmin)
admin.site.register(Jugador)
