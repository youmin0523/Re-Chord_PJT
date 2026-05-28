# Phase B frontend image — Vite build served by nginx with API proxy.
#
# Build context is repo root (so the image can read both frontend/ and
# deploy/nginx.conf). VITE_API_BASE is baked at build time because Vite
# inlines `import.meta.env.*` into the bundle.
#
#   docker build -f deploy/frontend.Dockerfile -t rechord-frontend \
#       --build-arg VITE_API_BASE=https://api.example.com .

# --- Stage 1: Vite production build -----------------------------------
FROM node:20-alpine AS build

ARG VITE_API_BASE=http://localhost:7860
ENV VITE_API_BASE=$VITE_API_BASE

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# --- Stage 2: nginx static server -------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:80/healthz > /dev/null || exit 1
