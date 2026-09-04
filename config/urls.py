"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin, auth
from django.contrib.auth import views as auth_views
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import include, path
from django.views.generic import RedirectView


def demo_login(request):
    if request.method == 'POST':
        email = (request.POST.get('email') or request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''

        user = auth.authenticate(request, email=email, password=password)

        if user is None and email.lower() == 'demo@inlinepadel.com' and password == 'demo':
            user = auth.authenticate(request, email=email, password='demo123')

        if user is not None:
            auth.login(request, user)
            return HttpResponseRedirect('/clubes/')

        return render(request, 'registration/login.html', {'error': 'Email o contraseña inválidos.'})
    return render(request, 'registration/login.html')


urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/login/', permanent=False), name='home'),
    path('accounts/login/', demo_login, name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path("admin/", admin.site.urls),
    path('clubes/', include('clubes.urls')),
    path('partidas/', include('partidas.urls')),
    path('social/', include('social.urls')),
    path('usuarios/', include('usuarios.urls')),
]
