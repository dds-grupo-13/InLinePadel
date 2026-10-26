from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include([
        path("usuarios/", include("usuarios.urls")),
        path("clubes/", include("clubes.urls")),
        path("partidas/", include("partidas.urls")),
        path("social/", include("social.urls")),
    ])),
    path("api-auth/", include("rest_framework.urls")),
]
