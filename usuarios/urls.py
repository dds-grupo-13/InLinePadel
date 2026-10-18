from rest_framework.routers import DefaultRouter

from .views import AuthViewSet, JugadorViewSet

router = DefaultRouter()
router.register("auth", AuthViewSet, basename="auth")
router.register("jugadores", JugadorViewSet, basename="jugador")

urlpatterns = router.urls
