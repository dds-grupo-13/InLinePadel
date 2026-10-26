from django.contrib import admin

from .models import Cancha, Club, Turno, Zona

admin.site.register([Zona, Club, Cancha, Turno])
