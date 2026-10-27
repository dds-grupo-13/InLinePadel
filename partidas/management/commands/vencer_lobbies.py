from django.core.management.base import BaseCommand
from django.utils import timezone

from clubes.models import Turno

from partidas.models import Lobby
from social.models import Invitacion


class Command(BaseCommand):
    help = (
        "Barrido de limpieza: cancela y notifica los lobbies vencidos que nadie tocó "
        "y cierra las partidas cuyo turno ya pasó. La regla del plazo se aplica "
        "también en cada pedido. Pensado para correr por cron."
    )

    def handle(self, *args, **options):
        ahora = timezone.now()

        vencidos = Lobby.objects.filter(Lobby.q_vencido(ahora)).select_related(
            "turno__cancha__club"
        )
        cancelados = 0
        for lobby in vencidos:
            if lobby.vencer_si_corresponde(ahora):
                cancelados += 1

        # Las cesiones pendientes de partidas que ya se jugaron pierden sentido.
        Invitacion.objects.filter(
            estado=Invitacion.Estado.PENDIENTE,
            lobby__estado=Lobby.Estado.COMPLETO,
            lobby__turno__fin__lt=ahora,
        ).update(estado=Invitacion.Estado.EXPIRADA)
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
