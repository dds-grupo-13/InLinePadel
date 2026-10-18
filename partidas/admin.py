from django.contrib import admin

from .models import Inscripcion, Lobby

admin.site.register([Lobby, Inscripcion])
