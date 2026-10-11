FROM python:3.11-slim

# Evitar prompts interactivos y optimizar logs de Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar y procesar audio
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copiar requerimientos e instalar paquetes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Crear directorios de datos
RUN mkdir -p /app/data/chroma /app/data/temp

# Exponer el puerto
EXPOSE 8000

# Comando de arranque (soporta la variable PORT asignada por Render/Railway/Koyeb)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
