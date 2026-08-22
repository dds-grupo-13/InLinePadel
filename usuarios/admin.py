from django.contrib import admin
from . import models

admin.site.register(models.Usuario)
admin.site.register(models.AdminSistema)
admin.site.register(models.AdminClub)
admin.site.register(models.Jugador)
