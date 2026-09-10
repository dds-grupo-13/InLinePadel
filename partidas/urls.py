from django.urls import path
from . import views

app_name = 'partidas'

urlpatterns = [
    path('turnos/<int:turno_id>/reservar/', views.crear_lobby_y_reserva, name='crear_reserva'),
    path('lobbies/', views.LobbyListView.as_view(), name='lobby_list'),
    path('lobbies/<int:pk>/', views.LobbyDetailView.as_view(), name='lobby_detail'),
    path('lobbies/<int:lobby_id>/unirse/', views.InscripcionCreateView.as_view(), name='unirse_lobby'),
    path('solicitudes/<int:pk>/aceptar/', views.AceptarSolicitudView.as_view(), name='aceptar_solicitud'),
    path('mis-partidos/', views.MisPartidosListView.as_view(), name='mis_partidos'),
    path('reservas/<int:reserva_id>/configurar-lobby/', views.LobbyUpdateView.as_view(), name='configurar_lobby'),
    path('reservas/<int:pk>/cancelar/', views.ReservaCancelView.as_view(), name='cancelar_reserva'),
    path('reservas/<int:pk>/check-in/', views.ReservaCheckInView.as_view(), name='reserva_checkin'),
]