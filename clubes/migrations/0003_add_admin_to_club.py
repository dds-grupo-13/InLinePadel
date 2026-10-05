from django.db import migrations, models
import django.db.models.deletion


def move_admin_relation(apps, schema_editor):
    AdminClub = apps.get_model("usuarios", "AdminClub")
    Club = apps.get_model("clubes", "Club")
    Usuario = apps.get_model("usuarios", "Usuario")

    admin_by_club = {}
    for admin in AdminClub.objects.exclude(club_id=None).order_by(
        "club_id", "usuario_id"
    ).iterator():
        admin_by_club.setdefault(admin.club_id, admin.usuario_id)

    for club_id, admin_id in admin_by_club.items():
        Club.objects.filter(pk=club_id).update(admin_id=admin_id)

    assigned_admin_ids = set(
        Club.objects.exclude(admin_id=None).values_list("admin_id", flat=True)
    )
    for club in Club.objects.filter(admin_id=None).select_related("habilitado_por"):
        usuario_id = club.habilitado_por_id
        if usuario_id in assigned_admin_ids:
            email = f"admin.club.{club.pk}@inlinepadel.local"
            usuario = Usuario.objects.create(
                email=email,
                is_active=True,
                is_staff=False,
                is_superuser=False,
                password="!",
            )
            usuario_id = usuario.pk
        AdminClub.objects.create(usuario_id=usuario_id, club_id=club.pk)
        Club.objects.filter(pk=club.pk).update(admin_id=usuario_id)
        assigned_admin_ids.add(usuario_id)


class Migration(migrations.Migration):

    dependencies = [
        ("clubes", "0002_initial"),
        ("usuarios", "0003_remove_jugador_categoria_manual_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="club",
            name="admin",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="club",
                to="usuarios.adminclub",
            ),
        ),
        migrations.RunPython(move_admin_relation, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="club",
            name="admin",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="club",
                to="usuarios.adminclub",
            ),
        ),
    ]
