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

# Optional: generate LoS topology (long, ~20 min). Default: use pre-built files from repo.
# To regenerate (e.g. after changing walls): docker build --build-arg BUILD_TOPOLOGY=1 ...
ARG BUILD_TOPOLOGY=0
RUN if [ "$BUILD_TOPOLOGY" = "1" ]; then python scripts/los_topology_builder.py 25x21; fi

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:5001/api/health || exit 1

CMD ["python", "services/api_server.py"]
