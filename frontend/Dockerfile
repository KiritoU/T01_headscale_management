FROM node:22-alpine AS builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/nginx/00-forwarded-proto-map.conf /etc/nginx/conf.d/00-forwarded-proto-map.conf
# Rendered to /etc/nginx/conf.d/default.conf at startup with ${DOWNLOAD_HOST} substituted.
COPY docker/nginx/default.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=6 --start-period=10s \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
