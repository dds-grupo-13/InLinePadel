from django.urls import path

from .views import (
	InvitacionCreateView,
	InvitacionesListView,
	ProcesarInvitacionView,
)

app_name = 'social'

urlpatterns = [
    path('lobbies/<int:lobby_id>/invitar/', InvitacionCreateView.as_view(), name='crear_invitacion'),
    path('mis-invitaciones/', InvitacionesListView.as_view(), name='mis_invitaciones'),
    path('procesar-invitacion/', ProcesarInvitacionView.as_view(), name='procesar_invitacion'),
]
