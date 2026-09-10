from django.urls import path

from .views import AgregarContactoView, JugadorUpdateView, PerfilCasualView
from .views_contactos import BuscarJugadoresView, RemoverContactoView

app_name = 'usuarios'

urlpatterns = [
    path('perfil/', PerfilCasualView.as_view(), name='perfil'),
    path('perfil/agregar/', AgregarContactoView.as_view(), name='perfil_agregar_contacto'),
    path('perfil/editar/', JugadorUpdateView.as_view(), name='editar_perfil'),
    path('perfil/buscar/', BuscarJugadoresView.as_view(), name='perfil_buscar'),
    path('perfil/remover/', RemoverContactoView.as_view(), name='perfil_remover_contacto'),
]
