from rest_framework.routers import DefaultRouter

from .views import InscripcionViewSet, LobbyViewSet

router = DefaultRouter()
router.register("lobbies", LobbyViewSet, basename="lobby")
router.register("inscripciones", InscripcionViewSet, basename="inscripcion")

urlpatterns = router.urls
