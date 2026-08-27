# Archives Infra

| Date | Chantier | Détail |
|---|---|---|
| 2026-08-18 | gzip + Brotli | **gzip** : `frontend/nginx.conf` — `gzip on`, niveau 6, seuil 1 Ko, `gzip_vary on`, types JSON/JS/CSS/SVG/fonts. **Brotli** : `frontend/Dockerfile` — stage `brotli-builder` (nginx:1.27-alpine, git/cmake/build-base, clone `ngx_brotli`, source nginx exacte via `${NGINX_VERSION}`, `--with-compat`) ; `.so` copiés dans `/usr/lib/nginx/modules/` ; `load_module` injecté en tête de `/etc/nginx/nginx.conf` (contexte main) ; directives `brotli on/static/level 6/min 1 Ko` dans le bloc server. `test -f` explicite : pas de fallback silencieux si les `.so` manquent. |
