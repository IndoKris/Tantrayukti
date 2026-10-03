# EcoTrack frontend: build with Node, serve the static bundle with nginx.
FROM node:22-slim AS build

WORKDIR /app

# Lockfile first, so a source change does not reinstall dependencies.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Baked in at build time: Vite inlines VITE_* variables into the bundle, so this
# cannot be changed by an environment variable at run time.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine AS serve

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q --spider http://localhost/ || exit 1
