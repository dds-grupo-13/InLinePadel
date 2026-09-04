from django.urls import path

from .views import AgregarContactoView, JugadorUpdateView, PerfilCasualView

app_name = 'usuarios'

urlpatterns = [
    path('perfil/', PerfilCasualView.as_view(), name='perfil'),
    path('perfil/agregar/', AgregarContactoView.as_view(), name='perfil_agregar_contacto'),
    path('perfil/editar/', JugadorUpdateView.as_view(), name='editar_perfil'),
]
