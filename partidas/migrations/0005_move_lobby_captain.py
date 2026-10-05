from django.db import migrations, models
import django.db.models.deletion


def move_captains(apps, schema_editor):
    Lobby = apps.get_model("partidas", "Lobby")
    Inscripcion = apps.get_model("partidas", "Inscripcion")

    for lobby in Lobby.objects.filter(capitan_id=None):
        captain = (
            Inscripcion.objects.filter(lobby_id=lobby.pk, numero_cupo=1)
            .values_list("jugador_id", flat=True)
            .first()
        )
        if captain is None:
            raise RuntimeError(
                "No se puede hacer obligatorio Lobby.capitan: "
                f"el lobby {lobby.pk} no tiene una inscripción en el cupo 1."
            )
        Lobby.objects.filter(pk=lobby.pk).update(capitan_id=captain)


class Migration(migrations.Migration):

    dependencies = [
        ("clubes", "0003_add_admin_to_club"),
        ("usuarios", "0004_remove_adminclub_club"),
        ("partidas", "0004_remove_ranking_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="lobby",
            name="capitan",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lobbies_capitaneados",
                to="usuarios.jugador",
            ),
        ),
        migrations.RunPython(move_captains, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lobby",
            name="capitan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lobbies_capitaneados",
                to="usuarios.jugador",
            ),
        ),
        migrations.RemoveField(
            model_name="inscripcion",
            name="rol",
        ),
    ]
