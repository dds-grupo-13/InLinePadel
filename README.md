# Guía de trabajo del proyecto

## Antes de empezar a escribir código

Antes de realizar cambios en el código:

1. Crear una nueva branch de Git:

```bash
git checkout -b nombre-de-la-rama
```

2. Subir el código a la rama siguiendo el flujo normal:

```bash
git add .
git commit -m "Descripción de los cambios"
```

3. Empujar la rama al repositorio remoto:

```bash
git push origin nombre-de-la-rama
```

Cuando estemos seguros de que funca, hacer un **Pull Request (PR)** y enviarlo a `main`.

---

## Para correr el proyecto

Ejecutar los siguientes pasos:

1. Crear el entorno virtual:

```bash
python -m venv venv
```

2. Activar el entorno virtual:

Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
source venv/bin/activate
```

3. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

4. Configurar la base de datos en el `.env` (copiar de `.env.example`) y
   aplicar migraciones + datos demo:

```bash
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

El comando `seed_demo_data` es idempotente: crea zonas, clubes, canchas,
turnos, partidas y los usuarios demo para la presentación. El despliegue con
Docker está en `../InLinePadel-Interfaz/docker-compose.yml`.

---

## Autenticación (JWT) y CORS

Variable de entorno (ver `.env.example`): `CORS_ALLOWED_ORIGINS`, orígenes del frontend separados por coma (por defecto `http://localhost:4200`).

Endpoints en `/api/usuarios/auth/`:

| Endpoint | Body | Respuesta |
|---|---|---|
| `POST login/` | `username`, `password` | `access`, `refresh`, `usuario` |
| `POST refresh/` | `refresh` | nuevo `access` y nuevo `refresh` (401 si es inválido o ya usado) |
| `POST logout/` (con Bearer) | `refresh` | 204; el refresh queda invalidado |

Las demás requests llevan `Authorization: Bearer <access>`. El access dura 15 minutos y el refresh 1 día; el refresh rota en cada uso y el anterior queda en la blacklist. Dar de baja una cuenta invalida todos sus refresh.

---

## Cambios en `models.py`

Si se realizan cambios en los archivos `models.py`, ejecutar:

1. Crear las migraciones:

```bash
python manage.py makemigrations
```

2. Aplicar las migraciones:

```bash
python manage.py migrate
```
