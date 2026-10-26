from rest_framework.routers import DefaultRouter

from .views import CanchaViewSet, ClubViewSet, TurnoViewSet, ZonaViewSet

router = DefaultRouter()
router.register("zonas", ZonaViewSet, basename="zona")
router.register("clubes", ClubViewSet, basename="club")
router.register("canchas", CanchaViewSet, basename="cancha")
router.register("turnos", TurnoViewSet, basename="turno")

urlpatterns = router.urls
