from django.urls import path

from .views import InvitacionCreateView

app_name = 'social'

urlpatterns = [
    path('lobbies/<int:lobby_id>/invitar/', InvitacionCreateView.as_view(), name='crear_invitacion'),
]
