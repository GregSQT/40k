FROM node:22-alpine AS build

WORKDIR /workspace

# deps frontend
COPY frontend/package.json frontend/package-lock.json /workspace/frontend/
RUN cd /workspace/frontend && npm ci

# repo complet (inclut shared/, scripts/, config/, etc.)
COPY . /workspace

# build sans typecheck bloquant
RUN cd /workspace/frontend && npx vite build

FROM nginx:1.27-alpine

COPY --from=build /workspace/frontend/dist /usr/share/nginx/html

RUN printf '%s\n' \
'server {' \
'    listen 80;' \
'    server_name _;' \
'    root /usr/share/nginx/html;' \
'    index index.html;' \
'' \
'    location / {' \
'        try_files $uri $uri/ /index.html;' \
'    }' \
'' \
'    location /api/ {' \
'        proxy_pass http://backend:5001/api/;' \
'        proxy_http_version 1.1;' \
'        proxy_set_header Host $host;' \
'        proxy_set_header X-Real-IP $remote_addr;' \
'        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
'        proxy_set_header X-Forwarded-Proto $scheme;' \
'    }' \
'}' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
