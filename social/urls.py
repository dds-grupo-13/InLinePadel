from rest_framework.routers import DefaultRouter

from .views import (
    ContactoViewSet,
    InvitacionViewSet,
    NotificacionViewSet,
    SolicitudAccesoViewSet,
)

router = DefaultRouter()
router.register("contactos", ContactoViewSet, basename="contacto")
router.register("invitaciones", InvitacionViewSet, basename="invitacion")
router.register("solicitudes", SolicitudAccesoViewSet, basename="solicitud")
router.register("notificaciones", NotificacionViewSet, basename="notificacion")

urlpatterns = router.urls
