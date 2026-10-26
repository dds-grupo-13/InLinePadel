from django.core.management.base import BaseCommand
from django.utils import timezone

from clubes.models import Turno

from partidas.models import Lobby


class Command(BaseCommand):
    help = (
        "Cancela los lobbies cuyo plazo venció sin completar cupos (liberando el "
        "turno) y cierra las partidas cuyo turno ya pasó. Pensado para correr por cron."
    )

    def handle(self, *args, **options):
        ahora = timezone.now()

        vencidos = Lobby.objects.filter(
            estado=Lobby.Estado.EN_FORMACION, plazo_limite__lt=ahora
        ).select_related("turno__cancha__club")
        cancelados = 0
        for lobby in vencidos:
            try:
                lobby._cancelar(Lobby.CanceladaPor.VENCIMIENTO)
                cancelados += 1
            except ValueError:
                continue

        jugados = Lobby.objects.filter(
            estado=Lobby.Estado.COMPLETO, turno__fin__lt=ahora
        ).update(estado=Lobby.Estado.JUGADO)
        cumplidos = Turno.objects.filter(
            estado=Turno.Estado.CONFIRMADO, fin__lt=ahora
        ).update(estado=Turno.Estado.CUMPLIDO)

        self.stdout.write(
            f"Lobbies cancelados: {cancelados} | partidas jugadas: {jugados} | "
            f"turnos cumplidos: {cumplidos}"
        )
