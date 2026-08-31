# Frontend multi-stage build for RAGForge
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
# Nginx config with API proxy to backend
RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location /api/ {\n\
        proxy_pass http://backend:8000;\n\
        proxy_http_version 1.1;\n\
        proxy_set_header Host $$host;\n\
        proxy_set_header X-Real-IP $$remote_addr;\n\
        proxy_set_header X-Forwarded-For $$proxy_add_x_forwarded_for;\n\
        proxy_set_header X-Forwarded-Proto $$scheme;\n\
        proxy_set_header X-Request-ID $$http_x_request_id;\n\
        proxy_read_timeout 300s;\n\
        proxy_buffering off;\n\
        proxy_cache off;\n\
    }\n\
    location /health {\n\
        proxy_pass http://backend:8000;\n\
        proxy_http_version 1.1;\n\
        proxy_set_header Host $$host;\n\
    }\n\
    location / {\n\
        try_files $$uri /index.html;\n\
    }\n\
    gzip on;\n\
    gzip_types text/plain text/css application/json application/javascript text/xml;\n\
    gzip_min_length 1024;\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
