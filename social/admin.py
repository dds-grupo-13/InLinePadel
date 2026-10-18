from django.contrib import admin

from .models import Contacto, Invitacion, Notificacion, SolicitudAcceso

admin.site.register([Notificacion, Contacto, SolicitudAcceso, Invitacion])
