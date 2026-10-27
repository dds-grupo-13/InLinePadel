# Servidor de Aplicación (diagrama de despliegue): backend Django + gunicorn
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# Aplica las migraciones y crea la tabla de caché (throttling compartido) al arrancar, y levanta la API
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
