FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.runtime.txt /app/requirements.runtime.txt
RUN pip install --no-cache-dir -r /app/requirements.runtime.txt

COPY . /app

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:5001/api/health || exit 1

# Serveur WSGI de PRODUCTION (waitress), pas le serveur de développement Werkzeug (F9).
# `services/wsgi.py` écoute sur 0.0.0.0 à l'intérieur du conteneur — sans quoi ni le reverse
# proxy ni un mapping de port ne joignent le backend (F15). L'exposition reste fermée par
# `docker-compose.yml`, qui ne publie plus ce port : seul nginx est publié.
CMD ["python", "-m", "services.wsgi"]
