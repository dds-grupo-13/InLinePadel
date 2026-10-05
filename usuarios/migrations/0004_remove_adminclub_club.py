from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("clubes", "0003_add_admin_to_club"),
        ("usuarios", "0003_remove_jugador_categoria_manual_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="adminclub",
            name="club",
        ),
    ]
