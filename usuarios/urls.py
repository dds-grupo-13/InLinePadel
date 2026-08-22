from django.urls import path

from .views import JugadorUpdateView

app_name = 'usuarios'

urlpatterns = [
    path('perfil/editar/', JugadorUpdateView.as_view(), name='editar_perfil'),
]
