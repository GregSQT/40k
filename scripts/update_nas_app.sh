#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/volume1/docker/40k/app"

cd "$APP_DIR"

echo "==> Git status"
git status -sb

echo "==> Pull latest main"
git pull --rebase origin main

echo "==> Rebuild and restart containers"
sudo docker compose up -d --build

echo "==> Health checks"
sudo docker compose ps
curl -fsS http://127.0.0.1:5001/api/health || true
curl -I http://127.0.0.1:8081 || true

echo "Done."