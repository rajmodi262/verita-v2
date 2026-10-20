# syntax=docker/dockerfile:1.7
# Verita web: build the SPA, serve it from unprivileged nginx, proxy /api to the API service.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# alpine-slim: no image-filter/xslt modules, so no libxml2/libpng/tiff to patch. Packages are
# upgraded at build time; CI fails on fixable High/Critical findings (grype --only-fixed).
FROM nginxinc/nginx-unprivileged:1.29-alpine-slim AS runtime
USER root
RUN apk upgrade --no-cache
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
