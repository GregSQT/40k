FROM node:22-alpine AS build

WORKDIR /workspace

# deps frontend
COPY frontend/package.json frontend/package-lock.json /workspace/frontend/
RUN cd /workspace/frontend && npm ci

# repo complet (inclut shared/, scripts/, config/, etc.)
COPY . /workspace

# build sans typecheck bloquant
RUN cd /workspace/frontend && VITE_API_URL=/api npx vite build

FROM nginx:1.27-alpine

COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

# Configuration VERSIONNÉE (`frontend/nginx.conf`) et non plus écrite en `printf` ici : elle
# porte désormais le TLS et les en-têtes de sécurité, qui ne se relisent pas en lignes échappées.
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# 443 en plus de 80 : le port 80 ne sert plus que la redirection vers HTTPS (F9).
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
