# Containerisation de l'application pour Synology NAS

## Objectif
Packager l'application dans des conteneurs Docker pour la deployer et la partager depuis un NAS Synology.

Ce document couvre:
- architecture cible
- fichiers Docker a creer
- gestion des volumes persistants
- deploiement sur Synology (Container Manager ou SSH)
- checklist de verification

## Hypothese de stack
- Backend: Flask (API Python)
- Frontend: React + Vite (servi en statique par Nginx)
- Orchestration: Docker Compose

Si la structure reelle differe, adapter les chemins et commandes.

## Architecture cible
- `backend`:
  - expose l'API sur le port `5000` (interne)
  - monte les donnees persistantes:
    - base utilisateur (`config/users.db`)
    - modeles IA (`ai/models/`)
    - logs/sorties runtime
- `frontend`:
  - build Vite en mode production
  - sert le build via Nginx sur `80` (interne), mappe en `8080` (host)
  - consomme l'API backend via variable d'environnement au build

Schema logique:
1. Utilisateur -> Frontend (`:8080`)
2. Frontend -> Backend (`backend:5000` via reseau Docker)
3. Backend -> volumes persistants (DB, modeles, logs)

## Fichiers a preparer (etape implementation)
1. `Dockerfile` backend
2. `frontend/Dockerfile` frontend
3. `docker-compose.yml`
4. `.dockerignore` (racine et eventuellement frontend)
5. (optionnel) `nginx.conf` pour le frontend

## Exemple de strategy Dockerfile backend
Principes:
- image Python slim
- installation dependances via `requirements.txt`
- copie du code
- utilisateur non-root
- commande de demarrage explicite (gunicorn recommande en prod)

Points de vigilance:
- ne pas coder de fallback silencieux sur les variables d'environnement
- lever une erreur explicite si une variable critique manque
- prevoir un healthcheck HTTP (`/health` si endpoint disponible)

## Exemple de strategy Dockerfile frontend
Principes:
- build stage Node (npm ci + npm run build)
- runtime stage Nginx
- copie du dossier `dist/` dans Nginx
- config Nginx avec fallback SPA vers `index.html` si besoin

## Exemple de squelette docker-compose
```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: wh40k-backend
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./config:/app/config
      - ./ai/models:/app/ai/models
      - ./runtime:/app/runtime
    environment:
      - FLASK_ENV=production
      # Ajouter ici les variables obligatoires
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 5s
      retries: 5

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: wh40k-frontend
    restart: unless-stopped
    ports:
      - "8080:80"
    depends_on:
      backend:
        condition: service_healthy
```

Note:
- adapter les chemins (`/app/...`) a la structure finale des Dockerfiles.
- si `curl` absent de l'image backend, utiliser une commande healthcheck equivalente.

## Volumes persistants recommandes
Persistants obligatoires:
- `config/users.db` (ou dossier `config/` si DB dans ce repertoire)
- `ai/models/` (modeles entraines)
- dossier runtime (logs, exports, artefacts)

Pourquoi:
- conserver les donnees apres restart/update
- separer image immutable et donnees mutable

## Deploiement sur Synology

### Option A - Container Manager (UI)
1. Build et push des images depuis machine de dev vers registry (Docker Hub/GHCR).
2. Sur Synology, ouvrir Container Manager.
3. Creer projet Compose et coller `docker-compose.yml`.
4. Renseigner variables d'environnement et chemins de volumes NAS.
5. Lancer le projet.

### Option B - SSH + Docker Compose
1. Se connecter en SSH au NAS.
2. Recuperer le repo (ou transferer uniquement compose + env).
3. Lancer:
   - `docker compose pull` (si images publiees)
   - `docker compose up -d`
4. Verifier:
   - `docker compose ps`
   - `docker compose logs --tail=200 backend`
   - `docker compose logs --tail=200 frontend`

## Reseau, acces externe, HTTPS
- ouvrir uniquement les ports necessaires (ex: 8080 ou 80/443 via reverse proxy)
- preferer reverse proxy Synology + certificat Let's Encrypt
- ne pas exposer directement des ports d'admin ou debug

## Compatibilite architecture CPU
Verifier architecture NAS:
- `amd64` (x86_64) ou `arm64`

Si besoin de multi-arch:
- buildx et publication manifest multi-plateforme

## Securite minimale
- images legeres et a jour
- execution non-root quand possible
- secrets via variables d'environnement (pas en dur dans les Dockerfiles)
- pas de fallback silencieux en cas de variable manquante

## Checklist avant mise en prod
- [ ] Dockerfiles backend/frontend crees
- [ ] compose valide et demarrage local OK
- [ ] volumes persistants verifies (DB, modeles, logs)
- [ ] healthchecks OK
- [ ] reverse proxy + HTTPS actifs
- [ ] logs consultables et rotation planifiee
- [ ] procedure de rollback definie (tag image precedent)

## Prochaine etape
Appliquer cette specification en code:
- creation des Dockerfiles
- creation du `docker-compose.yml`
- ajout des `.dockerignore`
- tests de build et run local
