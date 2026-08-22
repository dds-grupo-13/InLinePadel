from django.urls import path
from . import views

app_name = 'clubes'

urlpatterns = [
    path('', views.ClubListView.as_view(), name='club_list'),
    path('<int:club_id>/canchas/', views.CanchaListView.as_view(), name='cancha_list'),
    path('canchas/<int:cancha_id>/', views.CanchaDetailView.as_view(), name='cancha_detail'),
]