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

4. Ejecutar el servidor:

```bash
python manage.py runserver
```

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
