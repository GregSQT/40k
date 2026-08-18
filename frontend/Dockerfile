FROM node:22-alpine AS build

WORKDIR /workspace

# deps frontend
COPY frontend/package.json frontend/package-lock.json /workspace/frontend/
RUN cd /workspace/frontend && npm ci

# repo complet (inclut shared/, scripts/, config/, etc.)
COPY . /workspace

# build sans typecheck bloquant
RUN cd /workspace/frontend && VITE_API_URL=/api npx vite build

# Stage dédié : compilation de ngx_brotli contre la source nginx exacte de l'image finale.
# NGINX_VERSION est fourni par l'image de base nginx:1.27-alpine.
FROM nginx:1.27-alpine AS brotli-builder

RUN apk add --no-cache \
        git cmake build-base openssl-dev pcre2-dev zlib-dev linux-headers \
    && git clone --recurse-submodules --depth 1 \
        https://github.com/google/ngx_brotli /tmp/ngx_brotli \
    && wget -q "http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz" -P /tmp \
    && tar -xzf "/tmp/nginx-${NGINX_VERSION}.tar.gz" -C /tmp \
    && cd "/tmp/nginx-${NGINX_VERSION}" \
    && ./configure --with-compat --add-dynamic-module=/tmp/ngx_brotli \
    && make modules \
    && mkdir /tmp/brotli_modules \
    && cp objs/ngx_http_brotli_filter_module.so \
          objs/ngx_http_brotli_static_module.so \
          /tmp/brotli_modules/ \
    && test -f /tmp/brotli_modules/ngx_http_brotli_filter_module.so \
    && test -f /tmp/brotli_modules/ngx_http_brotli_static_module.so

FROM nginx:1.27-alpine

COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

# Configuration VERSIONNÉE (`frontend/nginx.conf`) et non plus écrite en `printf` ici : elle
# porte désormais le TLS et les en-têtes de sécurité, qui ne se relisent pas en lignes échappées.
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Modules brotli compilés dans le stage dédié contre la source nginx exacte.
# load_module exige les .so dans le contexte principal (/etc/nginx/nginx.conf) avant events {}.
# Si un .so manque, nginx refuse de démarrer — comportement voulu, pas de fallback silencieux.
COPY --from=brotli-builder /tmp/brotli_modules/ /usr/lib/nginx/modules/
RUN printf 'load_module modules/ngx_http_brotli_filter_module.so;\nload_module modules/ngx_http_brotli_static_module.so;\n\n' \
    | cat - /etc/nginx/nginx.conf > /tmp/nginx_main.conf \
    && mv /tmp/nginx_main.conf /etc/nginx/nginx.conf

# 443 en plus de 80 : le port 80 ne sert plus que la redirection vers HTTPS (F9).
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
