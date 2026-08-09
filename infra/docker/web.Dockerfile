# ── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /build

# Install deps first for layer caching
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --silent

# Copy source and build
COPY apps/web/ .

# VITE_BASE controls the asset prefix. For bank deployment use / (the default).
# For GitHub Pages use /Bank-Intelligence-Platform/ (set in vite.config.js default).
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE

RUN npm run build

# ── Stage 2: Serve ───────────────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Replace default nginx config with ASTRA's (includes /v1/ proxy + SPA fallback)
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm /etc/nginx/conf.d/*.conf.default 2>/dev/null || true

# Copy built React app
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
  CMD wget -qO- http://localhost/health || exit 1
